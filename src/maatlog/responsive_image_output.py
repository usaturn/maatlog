"""Publish responsive variants and track output ownership.

The variant cache under ``doctreedir`` is shared across builds and output
directories; the published copies under ``<outdir>/<imagedir>/maatlog/`` are
per-output state. This module copies cache artifacts to the output directory
without hardlinks and records which published files the current build owns, so
a later successful build can remove only its own stale files.

Nothing here imports Pillow: publication copies bytes and hashes files, it
never decodes an image.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sphinx.util import logging

from .errors import Diagnostic, MaatlogBuildError
from .image_contracts import FORMAT_EXTENSIONS, GeneratedVariant

__all__ = [
    "IMAGE_INVALID_VARIANT",
    "IMAGE_OUTPUT_UNWRITABLE",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "commit_owned_variants",
    "publish_variants",
]

#: A published variant failed adapter-boundary validation.
IMAGE_INVALID_VARIANT: Final = "maatlog.image.invalid-variant"

#: A published variant or ownership record could not be written.
IMAGE_OUTPUT_UNWRITABLE: Final = "maatlog.image.output-unwritable"

#: Ownership record inside the published ``maatlog`` directory.
MANIFEST_FILENAME: Final = ".manifest.json"

#: Only schema 1 exists; anything else is treated as invalid, never migrated.
MANIFEST_SCHEMA_VERSION: Final = 1

_BASENAME_RE: Final = re.compile(r"[A-Za-z0-9._-]+\Z")
_DIGEST_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_HASH_CHUNK_BYTES: Final = 1024 * 1024

logger = logging.getLogger(__name__)


def _is_safe_basename(name: str) -> bool:
    """Return True for a single safe path component (never ``.``/``..``)."""
    if not name or name in (".", ".."):
        return False
    if name == MANIFEST_FILENAME:
        return False
    if "/" in name or "\\" in name:
        return False
    return _BASENAME_RE.fullmatch(name) is not None


class _OwnershipManifest(BaseModel):
    """Strict ownership record: exact keys, schema 1, safe names, hex digests."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    schema_version: int = Field(alias="schema")
    builder: str
    files: dict[str, str]

    @field_validator("schema_version")
    @classmethod
    def _check_schema(cls, value: int) -> int:
        if value != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported ownership schema: {value!r}")
        return value

    @field_validator("builder")
    @classmethod
    def _check_builder(cls, value: str) -> str:
        if not value:
            raise ValueError("builder must be a non-empty string")
        return value

    @field_validator("files")
    @classmethod
    def _check_files(cls, value: dict[str, str]) -> dict[str, str]:
        for name, digest in value.items():
            if not _is_safe_basename(name):
                raise ValueError(f"unsafe owned basename: {name!r}")
            if _DIGEST_RE.fullmatch(digest) is None:
                raise ValueError(f"invalid digest for {name!r}")
        return value


def _invalid_variant(message: str, *, value: str | None = None) -> MaatlogBuildError:
    return MaatlogBuildError(
        [
            Diagnostic(
                code=IMAGE_INVALID_VARIANT,
                message=message,
                value=value,
                expected="a validated responsive variant artifact",
            )
        ]
    )


def _output_unwritable(message: str, *, value: str | None = None) -> MaatlogBuildError:
    return MaatlogBuildError(
        [
            Diagnostic(
                code=IMAGE_OUTPUT_UNWRITABLE,
                message=message,
                value=value,
                expected="a writable responsive image output directory",
            )
        ]
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _has_symlink_component(anchor: Path, candidate: Path) -> bool:
    """Return True when any component from *anchor* (exclusive) to *candidate* is a symlink."""
    try:
        relative_parts = candidate.relative_to(anchor).parts
    except ValueError:
        return False
    current = anchor
    for component in relative_parts:
        current /= component
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _reject_symlink_output_root(output_root: Path) -> None:
    """Reject an output root that would publish outside its directory."""
    for candidate in (output_root, output_root.parent, output_root.parent.parent):
        try:
            if candidate.is_symlink():
                raise _invalid_variant(
                    f"Responsive image output path contains a symbolic link: {candidate}",
                    value=str(output_root),
                )
        except OSError as error:
            raise _invalid_variant(
                f"Cannot validate responsive image output path: {error}",
                value=str(output_root),
            ) from error


def _validate_variant(variant: GeneratedVariant, *, cache_root: Path) -> Path:
    """Check *variant* against the cache; return its resolved cache file."""
    if not _is_safe_basename(variant.public_basename):
        raise _invalid_variant(
            f"Invalid responsive variant basename: {variant.public_basename!r}",
            value=variant.public_basename,
        )
    if variant.width <= 0 or variant.height <= 0 or variant.byte_size <= 0:
        raise _invalid_variant(
            f"Invalid responsive variant dimensions: {variant.public_basename!r}",
            value=variant.public_basename,
        )
    expected_suffix = FORMAT_EXTENSIONS[variant.image_format]
    if not variant.public_basename.endswith(expected_suffix):
        raise _invalid_variant(
            f"Responsive variant basename does not match its format: {variant.public_basename!r}",
            value=variant.public_basename,
        )
    cache_path = variant.cache_path
    try:
        lexical = Path(os.path.abspath(cache_path))
        root = Path(os.path.abspath(cache_root))
        inside_lexical = lexical.is_relative_to(root)
        resolved_inside = cache_path.resolve().is_relative_to(cache_root.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        raise _invalid_variant(
            f"Cannot validate responsive variant cache path: {variant.public_basename!r}",
            value=variant.public_basename,
        ) from error
    if not inside_lexical or not resolved_inside:
        raise _invalid_variant(
            f"Responsive variant cache escapes its directory: {variant.public_basename!r}",
            value=variant.public_basename,
        )
    try:
        if cache_path.is_symlink() or _has_symlink_component(cache_root, cache_path):
            raise _invalid_variant(
                f"Responsive variant cache contains a symbolic link: {variant.public_basename!r}",
                value=variant.public_basename,
            )
        if not cache_path.is_file():
            raise _invalid_variant(
                f"Responsive variant cache is not a regular file: {variant.public_basename!r}",
                value=variant.public_basename,
            )
        actual_size = cache_path.stat().st_size
    except MaatlogBuildError:
        raise
    except OSError as error:
        raise _invalid_variant(
            f"Cannot read responsive variant cache: {variant.public_basename!r}: {error}",
            value=variant.public_basename,
        ) from error
    if actual_size != variant.byte_size:
        raise _invalid_variant(
            f"Responsive variant size does not match its cache: {variant.public_basename!r}",
            value=variant.public_basename,
        )
    return cache_path


def publish_variants(
    variants: Sequence[GeneratedVariant],
    *,
    cache_root: Path,
    output_root: Path,
) -> dict[str, str]:
    """Copy cache artifacts to *output_root*; return basename to SHA-256 hex.

    Copies bytes (never hardlinks), so deleting the output never affects the
    cache and ``st_ino`` always differs. An identical existing published file
    is left in place, but existence alone is never trusted: the bytes are
    hashed first. A missing output with an intact cache is republished without
    re-encoding (encoding is the generator's job, not this function's).

    Raises :class:`MaatlogBuildError` with ``maatlog.image.invalid-variant``
    for validation failures (including two variants sharing a basename with
    different bytes) and ``maatlog.image.output-unwritable`` for output I/O
    failures. Empty input returns ``{}`` without creating *output_root*.
    """
    ordered = tuple(variants)
    if not ordered:
        return {}
    _reject_symlink_output_root(output_root)
    for variant in ordered:
        _validate_variant(variant, cache_root=cache_root)
    by_basename: dict[str, list[GeneratedVariant]] = {}
    for variant in ordered:
        by_basename.setdefault(variant.public_basename, []).append(variant)
    for basename, grouped in by_basename.items():
        if len(grouped) > 1:
            try:
                digests = {_hash_file(item.cache_path) for item in grouped}
            except OSError as error:
                raise _invalid_variant(
                    f"Cannot read responsive variant cache: {basename!r}: {error}",
                    value=basename,
                ) from error
            if len(digests) > 1:
                raise _invalid_variant(
                    f"Responsive variants share a basename with different bytes: {basename!r}",
                    value=basename,
                )
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _output_unwritable(
            f"Cannot create responsive image output directory: {error}",
            value=str(output_root),
        ) from error
    _reject_symlink_output_root(output_root)
    published: dict[str, str] = {}
    for basename in sorted(by_basename):
        variant = by_basename[basename][0]
        try:
            expected = _hash_file(variant.cache_path)
        except OSError as error:
            raise _invalid_variant(
                f"Cannot read responsive variant cache: {basename!r}: {error}",
                value=basename,
            ) from error
        destination = output_root / basename
        try:
            if destination.is_file() and not destination.is_symlink() and _hash_file(destination) == expected:
                published[basename] = expected
                continue
        except OSError as error:
            raise _output_unwritable(
                f"Cannot read responsive image output: {basename!r}: {error}",
                value=basename,
            ) from error
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=output_root, prefix=".maatlog-", delete=False) as stream:
                temporary = Path(stream.name)
                with variant.cache_path.open("rb") as source:
                    shutil.copyfileobj(source, stream)
            published[basename] = _hash_file(temporary)
            if published[basename] != expected:
                raise _invalid_variant(
                    f"Responsive variant cache changed during publication: {basename!r}",
                    value=basename,
                )
            os.replace(temporary, destination)
        except MaatlogBuildError:
            raise
        except OSError as error:
            raise _output_unwritable(
                f"Cannot publish responsive image: {basename!r}: {error}",
                value=basename,
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return published


def _warn_manifest_invalid(output_root: Path, reason: str) -> None:
    logger.warning(
        "Ignoring invalid responsive image ownership manifest in %r: %s",
        str(output_root),
        reason,
        type="maatlog",
        subtype="image.manifest-invalid",
    )


def commit_owned_variants(
    *,
    output_root: Path,
    builder_name: str,
    current: Mapping[str, str],
) -> None:
    """Record *current* ownership and remove only previously owned stale files.

    *current* maps published basenames to SHA-256 hex digests of the published
    bytes, as :func:`publish_variants` returns them. Deletion is limited to
    regular files listed in the previous manifest but absent from *current*
    whose bytes still match the recorded digest; symlinks, directories,
    modified files, unknown files, and path escapes are always kept. A broken
    previous record warns (``maatlog.image.manifest-invalid``) and deletes
    nothing, then the valid *current* record still replaces it. A different
    builder's record deletes nothing. When the manifest is missing and
    *current* is empty, the output directory is left untouched.

    A deletion failure keeps the old manifest so the next build retries; a
    manifest write failure raises :class:`MaatlogBuildError`.
    """
    wanted = dict(current)
    for name, digest in wanted.items():
        if not _is_safe_basename(name) or _DIGEST_RE.fullmatch(digest) is None:
            raise _invalid_variant(f"Invalid responsive ownership entry: {name!r}", value=name)
    manifest_path = output_root / MANIFEST_FILENAME
    if manifest_path.is_symlink():
        _warn_manifest_invalid(output_root, "manifest is a symbolic link")
        previous: dict[str, str] | None = None
    elif not manifest_path.is_file():
        if not wanted:
            return
        previous = {}
    else:
        try:
            raw = manifest_path.read_bytes()
            data = json.loads(raw.decode("utf-8"))
            manifest = _OwnershipManifest.model_validate(data)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            # ValueError covers JSON errors and pydantic ValidationError.
            _warn_manifest_invalid(output_root, str(error))
            previous = None
        else:
            if manifest.builder != builder_name:
                previous = {}
            else:
                previous = dict(manifest.files)
    if previous is None:
        deletable: set[str] = set()
    else:
        deletable = set(previous) - set(wanted)
    # Only paths that delete owned files or (re)write the manifest reach this
    # check: a missing manifest with nothing owned returns above and changes
    # nothing, even when an ancestor of the output root is a symbolic link.
    _reject_symlink_output_root(output_root)
    for name in sorted(deletable):
        assert previous is not None
        target = output_root / name
        try:
            if target.is_symlink() or not target.is_file():
                continue
            if _hash_file(target) != previous[name]:
                continue
        except OSError:
            return
        try:
            target.unlink()
        except OSError:
            return
    # A broken record with nothing to own still gets repaired below, so
    # unknown files stay while the manifest becomes valid again.
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _output_unwritable(
            f"Cannot create responsive image output directory: {error}",
            value=str(output_root),
        ) from error
    _reject_symlink_output_root(output_root)
    payload = {
        "schema": MANIFEST_SCHEMA_VERSION,
        "builder": builder_name,
        "files": {name: wanted[name] for name in sorted(wanted)},
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_root, prefix=".maatlog-", suffix=".json", mode="w", encoding="utf-8", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, manifest_path)
    except OSError as error:
        raise _output_unwritable(
            f"Cannot write responsive image ownership manifest: {error}",
            value=str(manifest_path),
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

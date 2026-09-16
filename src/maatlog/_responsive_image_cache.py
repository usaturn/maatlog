"""Verified, atomically published variant cache (issue #214, task 5).

Path, hash, JSON, temp file and atomic replace only: this module never imports
Pillow or the diagnostic contracts, so storage failures stay separable from
content failures. :class:`ImageProcessingError` and Pillow exceptions raised by
the *write* and *inspect* callbacks propagate untouched -- only the hit check
translates read, parse and verify failures into a miss, and a programming error
inside a callback resurfaces on the miss path instead of being swallowed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from .image_contracts import ImageFormat

__all__ = ["CACHE_SIDECAR_SCHEMA", "get_or_create"]

#: Sidecar schema version. Bumped when the record fields change, which retires
#: every sidecar whose ``schema`` no longer matches.
CACHE_SIDECAR_SCHEMA: Final = 1


def _sidecar_path(target: Path) -> Path:
    """Return the sidecar path recording *target*'s integrity facts."""
    return target.with_name(target.name + ".json")


def _hit_byte_size(
    *,
    target: Path,
    key: str,
    width: int,
    height: int,
    image_format: ImageFormat,
    inspect: Callable[[Path], tuple[int, int]],
) -> int | None:
    """Return the verified byte size when the cached pair is intact, else ``None``.

    A hit needs the image and its sidecar present with matching schema, key,
    format, expected dimensions, byte size and content hash, plus the *inspect*
    callback confirming the dimensions. Any corruption, missing sidecar or
    wrong bytes is a miss. Only this region is caught: the miss path below lets
    callback failures propagate for the caller to classify.
    """
    try:
        parsed = json.loads(_sidecar_path(target).read_bytes().decode("utf-8"))
        if not isinstance(parsed, dict):
            return None
        record = cast(dict[str, Any], parsed)
        if record.get("schema") != CACHE_SIDECAR_SCHEMA:
            return None
        if record.get("key") != key:
            return None
        if record.get("image_format") != image_format.value:
            return None
        if record.get("width") != width or record.get("height") != height:
            return None
        byte_size = record.get("byte_size")
        if type(byte_size) is not int or byte_size < 0:
            return None
        image_bytes = target.read_bytes()
        if len(image_bytes) != byte_size:
            return None
        if hashlib.sha256(image_bytes).hexdigest() != record.get("sha256"):
            return None
        if inspect(target) != (width, height):
            return None
        return byte_size
    except OSError, ValueError, TypeError, AttributeError:
        return None


def get_or_create(
    *,
    target: Path,
    key: str,
    width: int,
    height: int,
    image_format: ImageFormat,
    write: Callable[[Path], None],
    inspect: Callable[[Path], tuple[int, int]],
) -> int:
    """Return the verified final byte size of the cached variant at *target*.

    On a hit, *write* never runs. On a miss, the parent directory is created,
    *write* fills a caller-owned unique temporary file (never *target*
    itself), the temp is inspected, hashed and recorded in a sidecar written
    through its own unique temp file with flush and fsync, and both temps are
    published with :func:`os.replace` -- image first, sidecar second -- before
    the finished pair is re-inspected once (a single reload, never a retry).

    Only owned temps are removed in the ``finally`` block; existing targets and
    other processes' temps are never unlinked. When cleanup itself fails, the
    original error is kept and the cleanup detail is attached to it.
    """
    hit = _hit_byte_size(
        target=target, key=key, width=width, height=height, image_format=image_format, inspect=inspect
    )
    if hit is not None:
        return hit
    target.parent.mkdir(parents=True, exist_ok=True)
    owned: list[Path] = []
    primary: BaseException | None = None
    try:
        image_fd, image_name = tempfile.mkstemp(dir=target.parent, prefix="." + target.name + ".", suffix=".tmp")
        image_temp = Path(image_name)
        owned.append(image_temp)
        os.close(image_fd)
        write(image_temp)
        if inspect(image_temp) != (width, height):
            raise ValueError("encoded dimensions differ from request")
        with image_temp.open("rb") as stream:
            image_bytes = stream.read()
            os.fsync(stream.fileno())
        record = {
            "schema": CACHE_SIDECAR_SCHEMA,
            "key": key,
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
            "byte_size": len(image_bytes),
            "width": width,
            "height": height,
            "image_format": image_format.value,
        }
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        sidecar_target = _sidecar_path(target)
        sidecar_fd, sidecar_name = tempfile.mkstemp(
            dir=target.parent, prefix="." + sidecar_target.name + ".", suffix=".tmp"
        )
        sidecar_temp = Path(sidecar_name)
        owned.append(sidecar_temp)
        with os.fdopen(sidecar_fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(image_temp, target)
        os.replace(sidecar_temp, sidecar_target)
        verified = _hit_byte_size(
            target=target, key=key, width=width, height=height, image_format=image_format, inspect=inspect
        )
        if verified is None:
            raise ValueError("published variant failed verification")
        return verified
    except BaseException as exc:
        primary = exc
        raise
    finally:
        pending: list[str] = []
        for temporary in owned:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                pending.append(f"{temporary}: {cleanup_exc}")
        if pending:
            detail = "; ".join(pending)
            if primary is not None:
                primary.add_note(f"cache cleanup failed: {detail}")
            else:  # pragma: no cover - replaced temps are already gone
                raise OSError(f"cache cleanup failed: {detail}")

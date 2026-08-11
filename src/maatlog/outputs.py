"""Generated output manifests and safe stale cleanup for MaatLog-owned files.

Sphinx pickles ``environment.pickle`` after the read phase and before HTML
write / ``build-finished``. Page outputs are only known after archive
collection, so the owned-path sets are also written to a sidecar pickle under
``doctreedir`` and mirrored into domain ``generated_outputs`` for the Spec 02
schema.
"""

from __future__ import annotations

import pickle
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from sphinx.application import Sphinx
from sphinx.builders import Builder

from .archives import project_archives
from .config import MaatlogConfig
from .domain import MaatlogDomain
from .errors import Diagnostic, MaatlogBuildError
from .references import is_html_archive_builder
from .taxonomy import DomainIndex

Owner = Literal["pages", "feeds"]

# Sidecar next to environment.pickle — env dump runs before write/build-finished.
MANIFEST_FILENAME = "maatlog_generated_outputs.pickle"


@dataclass(frozen=True, slots=True)
class GeneratedOutputManifest:
    """Immutable record of relative output paths owned by one MaatLog subsystem."""

    owner: Owner
    paths: frozenset[str]


def output_unsafe(relative: PurePosixPath | str) -> MaatlogBuildError:
    """Build a ``maatlog.archive.output-unsafe`` error for *relative*."""
    text = relative.as_posix() if isinstance(relative, PurePosixPath) else str(relative)
    return MaatlogBuildError(
        [
            Diagnostic(
                code="maatlog.archive.output-unsafe",
                message=f"Unsafe generated output path: {text}",
                field="path",
                value=text,
                expected="a relative path under the Sphinx outdir without '..' or symlinks",
            )
        ]
    )


def safe_owned_path(outdir: Path, relative: PurePosixPath | str) -> Path:
    """Resolve *relative* under *outdir*, rejecting escape and symlink targets.

    Returns the candidate path under *outdir* (not necessarily resolved). Raises
    :class:`MaatlogBuildError` with ``maatlog.archive.output-unsafe`` when the
    path is absolute, contains ``..``, is a symlink, or resolves outside *outdir*.
    """
    rel = relative if isinstance(relative, PurePosixPath) else PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts == (".",):
        raise output_unsafe(rel)
    if any(part == "" or part == "." for part in rel.parts):
        raise output_unsafe(rel)

    candidate = outdir.joinpath(*rel.parts)
    component = outdir
    for part in rel.parts:
        component = component / part
        try:
            if component.is_symlink():
                raise output_unsafe(rel)
        except OSError as exc:
            raise output_unsafe(rel) from exc

    outdir_resolved = outdir.resolve()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise output_unsafe(rel) from exc
    if not resolved.is_relative_to(outdir_resolved):
        raise output_unsafe(rel)
    return candidate


def _path_set(manifest_or_paths: GeneratedOutputManifest | Collection[str]) -> set[str]:
    if isinstance(manifest_or_paths, GeneratedOutputManifest):
        return set(manifest_or_paths.paths)
    return set(manifest_or_paths)


def commit_generated_outputs(
    outdir: Path,
    previous: GeneratedOutputManifest | Collection[str],
    current: GeneratedOutputManifest | Collection[str],
) -> None:
    """Delete owned files in *previous* that are absent from *current*.

    Only paths present in the previous owned set and missing from the current
    set are removed. Unowned files are never touched. Symlinks and path escape
    attempts raise :class:`MaatlogBuildError` instead of deleting.
    """
    stale = _path_set(previous) - _path_set(current)
    for relative in sorted(stale):
        target = safe_owned_path(outdir, PurePosixPath(relative))
        if target.is_file() and not target.is_symlink():
            target.unlink()


def relative_builder_output_path(builder: Builder, pagename: str) -> str:
    """Return the outdir-relative posix path for *pagename* via the Builder API."""
    get_outfilename = getattr(builder, "get_outfilename", None)
    if not callable(get_outfilename):
        builder_name = getattr(builder, "name", type(builder))
        msg = f"builder {builder_name!r} has no get_outfilename"
        raise TypeError(msg)
    out_path = Path(cast(Any, get_outfilename(pagename)))
    return out_path.relative_to(Path(builder.outdir)).as_posix()


def page_output_paths(app: Sphinx) -> frozenset[str]:
    """Compute relative output paths for the current archive page projection."""
    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    index = cast(DomainIndex | None, domain.data.get("index"))
    if index is None:
        return frozenset()

    config = MaatlogConfig.from_sphinx(app.config)
    pages = project_archives(
        index,
        root=config.archive_docname,
        page_size=config.page_size,
        timezone=config.timezone,
    )
    outdir = Path(app.outdir)
    paths: set[str] = set()
    for page in pages:
        relative = relative_builder_output_path(app.builder, page.docname)
        safe_owned_path(outdir, PurePosixPath(relative))
        paths.add(relative)
    return frozenset(paths)


def _as_path_set(value: object) -> set[str]:
    if isinstance(value, (set, frozenset, list, tuple)):
        return {item for item in cast(Collection[object], value) if isinstance(item, str)}
    return set()


def ensure_generated_outputs(raw: object) -> dict[str, set[str]]:
    """Normalize a mapping of owner → path set with independent pages/feeds."""
    if not isinstance(raw, Mapping):
        return {"pages": set(), "feeds": set()}
    mapping = cast(Mapping[object, object], raw)
    return {
        "pages": _as_path_set(mapping.get("pages")),
        "feeds": _as_path_set(mapping.get("feeds")),
    }


def manifest_path(doctreedir: Path) -> Path:
    return Path(doctreedir) / MANIFEST_FILENAME


def load_persisted_outputs(doctreedir: Path) -> dict[str, set[str]]:
    """Load independent page/feed path sets from the sidecar pickle, if present."""
    path = manifest_path(doctreedir)
    if not path.is_file():
        return {"pages": set(), "feeds": set()}
    try:
        with path.open("rb") as handle:
            raw = pickle.load(handle)
    except OSError, pickle.PickleError, AttributeError, TypeError, ValueError:
        return {"pages": set(), "feeds": set()}
    return ensure_generated_outputs(raw)


def persist_outputs(doctreedir: Path, outputs: Mapping[str, Collection[str]]) -> None:
    """Write page/feed path sets to the sidecar pickle (deterministic path order)."""
    payload = {
        "pages": set(outputs.get("pages", ())),
        "feeds": set(outputs.get("feeds", ())),
    }
    path = manifest_path(doctreedir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(payload, handle, pickle.HIGHEST_PROTOCOL)


def get_owned_paths(domain: MaatlogDomain, owner: Owner) -> set[str]:
    """Return a mutable copy of stored relative paths for *owner* from domain data."""
    outputs = ensure_generated_outputs(domain.data.get("generated_outputs"))
    return set(outputs[owner])


def store_owned_paths(domain: MaatlogDomain, owner: Owner, paths: Collection[str]) -> None:
    """Replace the domain path set for *owner* without mutating the other owner."""
    outputs = ensure_generated_outputs(domain.data.get("generated_outputs"))
    outputs[owner] = set(paths)
    domain.data["generated_outputs"] = outputs


def commit_page_outputs(app: Sphinx, exception: Exception | None) -> None:
    """On successful HTML builds, remove stale archive pages and store the new manifest.

    No-ops when *exception* is set or the builder is not html/dirhtml.
    Reads previous page paths from the doctreedir sidecar (and domain mirror),
    never mutates ``feeds`` beyond preserving them on persist.
    """
    if exception is not None:
        return
    if not is_html_archive_builder(app.builder):
        return

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    doctreedir = Path(app.doctreedir)
    persisted = load_persisted_outputs(doctreedir)
    # Domain may hold same-process state; sidecar is authoritative across builds.
    previous = set(persisted["pages"]) | get_owned_paths(domain, "pages")
    current = page_output_paths(app)

    commit_generated_outputs(
        Path(app.outdir),
        GeneratedOutputManifest(owner="pages", paths=frozenset(previous)),
        GeneratedOutputManifest(owner="pages", paths=current),
    )

    store_owned_paths(domain, "pages", current)
    # Preserve feeds from the sidecar. Feed ownership is updated only by
    # ``write_feeds_after_success`` (runs after this handler on build-finished).
    feeds = set(persisted["feeds"])
    persist_outputs(doctreedir, {"pages": current, "feeds": feeds})

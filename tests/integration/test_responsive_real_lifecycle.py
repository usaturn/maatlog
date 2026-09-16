"""Real-generator incremental lifecycle tests (issue #217, task E/T3).

Every test drives the normal ``maatlog_responsive_images = True`` path with
the default Pillow backend -- no fake generator, no injected candidate files.
Rebuilds reuse the same srcdir/outdir/doctreedir through :func:`reopen`
(``freshenv=False``), so Sphinx itself decides what is stale. The
``_encode_variant`` observation wrappers either count or forbid real encodes;
they never replace the encoder's output.

The page set below is the full consumer surface of
:func:`fixtures.responsive_real_project.project_files` at ``post_count=15``,
``page_size=6``: home, every post, the top-only and representative-only
shapes, the ``post-list`` page, archive pages 1-3, and the tag/category/
author/month taxonomy pages.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from conftest import SphinxFactory
from fixtures.responsive_image_fixtures import make_test_png
from fixtures.responsive_real_inspect import (
    EncodeCounter,
    cache_dir,
    cache_files,
    collect_managed_refs,
    file_snapshot,
    forbidden_encode,
    local_image_path,
    managed_image_urls,
    manifest_basenames,
    page_path,
    published_variants,
    reopen,
    variant_dir,
)
from fixtures.responsive_real_project import image_cases, project_config, project_files
from PIL import Image
from sphinx.application import Sphinx

import maatlog.responsive_images as responsive_backend
from maatlog.errors import MaatlogBuildError
from maatlog.images import IMAGE_INVALID, IMAGE_MISSING
from maatlog.responsive_image_build import responsive_manifest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from collections.abc import Set as AbstractSet

_SOURCE_NAME: Final = "photo.jpg"
_SOURCE_KEY: Final = "images/photo.jpg"

#: Docnames expected to carry at least one managed ``<img>`` at
#: ``post_count=15``, ``page_size=6`` (18 posts total, all in 2026-07).
_CONSUMER_DOCNAMES: Final[tuple[str, ...]] = (
    "index",
    "listing",
    "top-only",
    "representative-only",
    *(f"posts/p{index:02d}" for index in range(1, 16)),
    "nested/blog",
    "nested/blog/page/2",
    "nested/blog/page/3",
    "nested/blog/tag/integration",
    "nested/blog/category/photos",
    "nested/blog/author/alice",
    "nested/blog/month/2026-07",
    "nested/blog/month/2026-07/page/2",
    "nested/blog/month/2026-07/page/3",
)


def _build(
    make_sphinx: SphinxFactory,
    *,
    builder: str = "html",
    feeds: bool = False,
    files: Mapping[str, str | bytes] | None = None,
    config: Mapping[str, object] | None = None,
) -> Sphinx:
    merged = project_config(enabled=True, page_size=6)
    merged["maatlog_generate_feeds"] = feeds
    if config is not None:
        merged.update(config)
    app = make_sphinx(
        files=files if files is not None else project_files(source_name=_SOURCE_NAME, post_count=15),
        config=merged,
        builder=builder,
    )
    app.build()
    return app


def _assert_consumers(
    app: Sphinx,
    expected: set[str],
    pages: Sequence[str] = _CONSUMER_DOCNAMES,
    extra_published: AbstractSet[str] = frozenset(),
) -> None:
    """Every expected page references the published candidates -- and only them.

    ``collect_managed_refs`` parses emitted HTML, so an un-rewritten consumer
    page surfaces as stale basenames rather than disappearing silently. Files a
    test deliberately planted in the variant directory (sentinels, tampered
    owned names) go in *extra_published*.
    """
    outdir = Path(app.outdir)
    refs = collect_managed_refs(outdir)
    expected_pages = {page_path(app.builder.name, docname) for docname in pages}
    assert set(refs) == expected_pages, (
        f"managed images on unexpected pages: missing={sorted(expected_pages - set(refs))} "
        f"extra={sorted(set(refs) - expected_pages)}"
    )
    seen: set[str] = set()
    for names in refs.values():
        seen |= names
    assert seen == expected, f"pages reference {sorted(seen ^ expected)} unexpectedly"
    assert set(published_variants(outdir)) == expected | extra_published


def _assert_decodable(published: Mapping[str, bytes]) -> None:
    for name, data in published.items():
        with Image.open(BytesIO(data)) as image:
            image.load()
            assert image.format in {"JPEG", "PNG", "WEBP"}, name
            assert not image.getexif(), name


def _rewrite_for_reread(path: Path, content: str | bytes) -> None:
    """Rewrite *path* with a bumped mtime so Sphinx must re-read its owner."""
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    future = time.time_ns() + 2_000_000_000
    os.utime(path, ns=(future, future))


def _codes(error: pytest.ExceptionInfo[MaatlogBuildError]) -> list[str]:
    return [diagnostic.code for diagnostic in error.value.diagnostics]


# ---------------------------------------------------------------------------
# Unchanged rebuilds reuse the real cache end to end (AC17, AC21)


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_real_unchanged_does_not_encode(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    app = _build(make_sphinx, builder=builder)
    manifest_before = dict(responsive_manifest(app.env))
    public_before = file_snapshot(variant_dir(Path(app.outdir)))
    cache_before = file_snapshot(cache_dir(app))
    monkeypatch.setattr(responsive_backend, "_encode_variant", forbidden_encode())
    rebuilt = reopen(app)
    rebuilt.build()
    assert dict(responsive_manifest(rebuilt.env)) == manifest_before
    assert file_snapshot(variant_dir(Path(rebuilt.outdir))) == public_before
    assert file_snapshot(cache_dir(rebuilt)) == cache_before
    _assert_consumers(rebuilt, set(manifest_basenames(rebuilt)))


def test_real_unchanged_with_feeds_does_not_encode(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _build(make_sphinx, feeds=True)
    feed_before = (Path(app.outdir) / "nested" / "blog" / "atom.xml").read_bytes()
    public_before = file_snapshot(variant_dir(Path(app.outdir)))
    monkeypatch.setattr(responsive_backend, "_encode_variant", forbidden_encode())
    rebuilt = reopen(app)
    rebuilt.build()
    assert file_snapshot(variant_dir(Path(rebuilt.outdir))) == public_before
    assert (Path(rebuilt.outdir) / "nested" / "blog" / "atom.xml").read_bytes() == feed_before
    _assert_consumers(rebuilt, set(manifest_basenames(rebuilt)))


# ---------------------------------------------------------------------------
# Source changes produce new candidates everywhere they are consumed (AC18)


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("restore_mtime", [False, True])
def test_real_image_only_change_rewrites_consumers(
    make_sphinx: SphinxFactory,
    monkeypatch: pytest.MonkeyPatch,
    builder: str,
    restore_mtime: bool,
) -> None:
    app = _build(make_sphinx, builder=builder)
    old_entry = responsive_manifest(app.env)[_SOURCE_KEY]
    old_names = manifest_basenames(app)
    source = Path(app.srcdir) / "images" / _SOURCE_NAME
    stat = source.stat()
    source.write_bytes(image_cases()["portrait.jpg"].payload)
    if restore_mtime:
        # Content changed but the timestamp did not: change detection must come
        # from the revalidation hash, not from Sphinx's mtime tracking.
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert source.stat().st_mtime_ns == stat.st_mtime_ns
    counter = EncodeCounter(monkeypatch)
    rebuilt = reopen(app)
    rebuilt.build()
    entry = responsive_manifest(rebuilt.env)[_SOURCE_KEY]
    assert entry.identity.content_hash != old_entry.identity.content_hash
    assert [variant.width for variant in entry.variants] == [480, 768, 900]
    assert counter.calls == 3
    new_names = manifest_basenames(rebuilt)
    assert old_names.isdisjoint(new_names)
    outdir = Path(rebuilt.outdir)
    published = published_variants(outdir)
    assert set(published) == new_names
    _assert_decodable(published)
    for name in old_names:
        assert not (variant_dir(outdir) / name).exists()
    _assert_consumers(rebuilt, new_names)


# ---------------------------------------------------------------------------
# Config and toggle transitions (AC19, AC25)


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_real_width_and_toggle_transitions(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    app = _build(make_sphinx, builder=builder)
    base_names = manifest_basenames(app)
    assert len(base_names) == 6
    original = (Path(app.outdir) / "_images" / _SOURCE_NAME).read_bytes()
    # Every later step must be served by the real cache: encoding is forbidden.
    monkeypatch.setattr(responsive_backend, "_encode_variant", forbidden_encode())

    narrow = reopen(app, overrides={"maatlog_responsive_image_widths": (480,)})
    narrow.build()
    names_480 = manifest_basenames(narrow)
    assert len(names_480) == 2  # 480w plus the natural-width candidate
    assert names_480 <= base_names
    _assert_consumers(narrow, names_480)
    for name in base_names - names_480:
        assert not (variant_dir(Path(narrow.outdir)) / name).exists()

    wide = reopen(narrow, overrides={"maatlog_responsive_image_widths": (768,)})
    wide.build()
    names_768 = manifest_basenames(wide)
    assert len(names_768) == 2
    assert names_768 <= base_names
    _assert_consumers(wide, names_768)
    for name in names_480 - names_768:
        assert not (variant_dir(Path(wide.outdir)) / name).exists()

    off = reopen(wide, overrides={"maatlog_responsive_images": False})
    off.build()
    assert responsive_manifest(off.env) == {}
    assert published_variants(Path(off.outdir)) == {}
    ownership = json.loads((variant_dir(Path(off.outdir)) / ".manifest.json").read_text(encoding="utf-8"))
    assert ownership["files"] == {}
    # Zero dangling references: no emitted page may still name a variant.
    for page in Path(off.outdir).rglob("*.html"):
        assert managed_image_urls(page.read_text(encoding="utf-8")) == set(), page.name
        assert "_images/maatlog/" not in page.read_text(encoding="utf-8"), page.name
    assert (Path(off.outdir) / "_images" / _SOURCE_NAME).read_bytes() == original

    on = reopen(off)
    on.build()
    assert manifest_basenames(on) == base_names
    assert set(published_variants(Path(on.outdir))) == base_names
    _assert_consumers(on, base_names)
    assert (Path(on.outdir) / "_images" / _SOURCE_NAME).read_bytes() == original


# ---------------------------------------------------------------------------
# Ownership: removing a source's last reference cleans only owned files (AX02)


def _post_with_image_and_top(slug: str, day: int, image: str) -> str:
    title = slug.replace("-", " ").title()
    return (
        f":maatlog-post: true\n:maatlog-slug: {slug}\n"
        f":maatlog-published-at: 2026-07-{day:02d}T09:00:00Z\n"
        f":maatlog-image: {image}\n\n"
        f"{title}\n{'=' * len(title)}\n\n"
        f".. maatlog:maattop:: {image}\n   :alt: Top image\n\nBody.\n"
    )


def _post_without_images(slug: str, day: int) -> str:
    title = slug.replace("-", " ").title()
    return (
        f":maatlog-post: true\n:maatlog-slug: {slug}\n"
        f":maatlog-published-at: 2026-07-{day:02d}T09:00:00Z\n\n"
        f"{title}\n{'=' * len(title)}\n\nBody.\n"
    )


def test_real_removed_reference_cleans_only_owned(make_sphinx: SphinxFactory) -> None:
    files = project_files(source_name=_SOURCE_NAME, post_count=15)
    files["images/rgba.png"] = image_cases()["rgba.png"].payload
    files["representative-only.rst"] = _post_with_image_and_top("representative-only", 17, "images/rgba.png")
    app = _build(make_sphinx, files=files)
    manifest = responsive_manifest(app.env)
    assert set(manifest) == {_SOURCE_KEY, "images/rgba.png"}
    rgba_names = {variant.public_basename for variant in manifest["images/rgba.png"].variants}
    assert rgba_names
    photo_names = manifest_basenames(app) - rgba_names
    output = variant_dir(Path(app.outdir))
    sentinel = output / "sentinel.bin"
    sentinel.write_bytes(b"not-owned-by-maatlog")
    # A file with an owned name but different bytes is not ours to delete.
    tampered = sorted(rgba_names)[0]
    (output / tampered).write_bytes(b"tampered-by-someone-else")
    _rewrite_for_reread(Path(app.srcdir) / "representative-only.rst", _post_without_images("representative-only", 17))
    rebuilt = reopen(app)
    rebuilt.build()
    manifest_after = responsive_manifest(rebuilt.env)
    assert "images/rgba.png" not in manifest_after
    assert _SOURCE_KEY in manifest_after
    outdir = Path(rebuilt.outdir)
    for name in rgba_names - {tampered}:
        assert not (variant_dir(outdir) / name).exists()
    assert (variant_dir(outdir) / tampered).read_bytes() == b"tampered-by-someone-else"
    assert sentinel.read_bytes() == b"not-owned-by-maatlog"
    for name in photo_names:
        assert (variant_dir(outdir) / name).is_file()
    assert (outdir / "_images" / _SOURCE_NAME).is_file()
    assert (outdir / "_images" / "body.png").is_file()
    _assert_consumers(
        rebuilt,
        photo_names,
        pages=tuple(docname for docname in _CONSUMER_DOCNAMES if docname != "representative-only"),
        extra_published={"sentinel.bin", tampered},
    )


# ---------------------------------------------------------------------------
# Failures never clean up: owned state survives a failed rebuild


def test_real_missing_referenced_source_fails(make_sphinx: SphinxFactory, tmp_path: Path) -> None:
    # A spaced source name keeps the image out of doctree bodies, matching the
    # front-matter-only reference shape the revalidation path is specified for.
    files = project_files(source_name="my photo.png", post_count=15)
    app = _build(make_sphinx, files=files)
    key = "images/my photo.png"
    assert key in responsive_manifest(app.env)
    public_before = file_snapshot(variant_dir(Path(app.outdir)))
    source = Path(app.srcdir) / "images" / "my photo.png"
    payload = source.read_bytes()

    source.unlink()
    with pytest.raises(MaatlogBuildError) as missing:
        reopen(app).build()
    assert _codes(missing) == [IMAGE_MISSING]
    assert file_snapshot(variant_dir(Path(app.outdir))) == public_before

    outside = tmp_path / "outside.png"
    outside.write_bytes(image_cases()["rgba.png"].payload)
    source.symlink_to(outside)
    with pytest.raises(MaatlogBuildError) as invalid:
        reopen(app).build()
    assert _codes(invalid) == [IMAGE_INVALID]
    assert file_snapshot(variant_dir(Path(app.outdir))) == public_before

    source.unlink()
    source.write_bytes(payload)
    recovered = reopen(app)
    recovered.build()
    assert file_snapshot(variant_dir(Path(recovered.outdir))) == public_before
    _assert_consumers(recovered, manifest_basenames(recovered))


# ---------------------------------------------------------------------------
# Output loss republishes from the real cache without re-encoding (AX02)


@pytest.mark.parametrize("scope", ["outdir", "variant"])
def test_real_output_loss_republishes_cache(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    app = _build(make_sphinx)
    names = manifest_basenames(app)
    public_before = file_snapshot(variant_dir(Path(app.outdir)))
    if scope == "outdir":
        shutil.rmtree(Path(app.outdir))
    else:
        (variant_dir(Path(app.outdir)) / sorted(names)[0]).unlink()
    monkeypatch.setattr(responsive_backend, "_encode_variant", forbidden_encode())
    rebuilt = reopen(app)
    rebuilt.build()
    assert file_snapshot(variant_dir(Path(rebuilt.outdir))) == public_before
    _assert_decodable(published_variants(Path(rebuilt.outdir)))
    _assert_consumers(rebuilt, names)


# ---------------------------------------------------------------------------
# A corrupt cache entry re-encodes through the real backend (AX04)


@pytest.mark.parametrize("target", ["payload", "sidecar"])
def test_real_corrupt_cache_recovers(make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    app = _build(make_sphinx)
    images = [path for path in cache_files(app) if path.suffix in {".jpg", ".png", ".webp"}]
    assert images
    victim = images[0]
    sidecar = victim.with_name(victim.name + ".json")
    if target == "payload":
        victim.write_bytes(victim.read_bytes() + b"\x00")
    else:
        assert sidecar.is_file()
        sidecar.write_text("{}\n", encoding="utf-8")
    counter = EncodeCounter(monkeypatch)
    rebuilt = reopen(app)
    rebuilt.build()
    assert counter.calls == 1
    image_bytes = victim.read_bytes()
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert record["sha256"] == sha256(image_bytes).hexdigest()
    assert record["byte_size"] == len(image_bytes)
    with Image.open(victim) as image:
        image.load()
        assert (image.width, image.height) == (record["width"], record["height"])
    _assert_decodable(published_variants(Path(rebuilt.outdir)))
    _assert_consumers(rebuilt, manifest_basenames(rebuilt))


# ---------------------------------------------------------------------------
# Source replacement and post removal keep originals and unmanaged files


def test_real_source_replacement_preserves_originals(make_sphinx: SphinxFactory) -> None:
    avatar_payload = make_test_png(320, 320)
    files = project_files(source_name=_SOURCE_NAME, post_count=15)
    files["images/avatar.png"] = avatar_payload
    config = {
        "maatlog_author_profiles": {
            "alice": {"role": "Editor", "featured_posts": ["p01"], "avatar": "images/avatar.png"}
        }
    }
    app = _build(make_sphinx, files=files, config=config)
    outdir = Path(app.outdir)
    assert (outdir / "_images" / "avatar.png").read_bytes() == avatar_payload
    body_bytes = (outdir / "_images" / "body.png").read_bytes()
    unmanaged = outdir / "notes.txt"
    unmanaged.write_text("keep me", encoding="utf-8")

    portrait = image_cases()["portrait.jpg"].payload
    _rewrite_for_reread(Path(app.srcdir) / "images" / _SOURCE_NAME, portrait)
    replaced = reopen(app)
    replaced.build()
    assert (Path(replaced.outdir) / "_images" / _SOURCE_NAME).read_bytes() == portrait
    assert (Path(replaced.outdir) / "_images" / "avatar.png").read_bytes() == avatar_payload
    assert (Path(replaced.outdir) / "_images" / "body.png").read_bytes() == body_bytes
    assert unmanaged.read_text(encoding="utf-8") == "keep me"
    _assert_consumers(replaced, manifest_basenames(replaced))

    srcdir = Path(app.srcdir)
    index = (srcdir / "index.rst").read_text(encoding="utf-8")
    assert "   posts/p15\n" in index
    _rewrite_for_reread(srcdir / "index.rst", index.replace("   posts/p15\n", ""))
    (srcdir / "posts" / "p15.md").unlink()
    rebuilt = reopen(replaced)
    rebuilt.build()
    outdir2 = Path(rebuilt.outdir)
    # Sphinx does not delete the removed document's stale HTML page on an
    # incremental rebuild; it stays behind referencing the still-published
    # photo candidates, so it remains a managed consumer page.
    assert (outdir2 / "posts" / "p15.html").is_file()
    assert (outdir2 / "_images" / _SOURCE_NAME).read_bytes() == portrait
    assert (outdir2 / "_images" / "avatar.png").read_bytes() == avatar_payload
    assert (outdir2 / "_images" / "body.png").read_bytes() == body_bytes
    assert unmanaged.read_text(encoding="utf-8") == "keep me"
    # p15's image is still referenced by the other posts: nothing is removed.
    _assert_consumers(rebuilt, manifest_basenames(rebuilt))
    assert local_image_path(outdir2, "index.html", "_images/photo.jpg").read_bytes() == portrait

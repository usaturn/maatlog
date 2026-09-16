"""Incremental responsive-image lifecycle over one project (issue #215 lane C, Task 4).

Each test builds once with ``make_sphinx`` and then rebuilds the SAME
srcdir/confdir/outdir/doctreedir through ``reopen_build`` (``freshenv=False``,
never ``force_all=True``). ``maatlog_generate_feeds=False`` keeps the focus on
image-only updates; one dedicated test proves the feeds-enabled path preserves
the originals shared with Atom feeds, social metadata, and avatars.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from conftest import SphinxFactory
from fixtures.responsive_build_fixtures import (
    FILES,
    PROBE,
    RecordingGenerator,
    _new_app,  # pyright: ignore[reportPrivateUsage]
    record_page_context,
    reopen_build,
)
from fixtures.responsive_image_fixtures import FakeVariantGenerator, make_test_png
from sphinx.application import Sphinx
from sphinx.builders import Builder as SphinxBuilder
from sphinx.errors import ExtensionError
from sphinx.util.logging import NAMESPACE as SPHINX_LOG_NAMESPACE

from maatlog.domain import MaatlogDomain
from maatlog.errors import Diagnostic, MaatlogBuildError
from maatlog.image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    IMAGE_ENCODE_FAILED,
    GeneratedVariant,
    ImageProcessingError,
    SourceImageProbe,
    VariantRequest,
    compute_variant_key,
    register_variant_generator_factory,
    variant_cache_relpath,
)
from maatlog.images import IMAGE_INVALID, IMAGE_MISSING
from maatlog.responsive_image_build import responsive_manifest


def _base_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "maatlog_responsive_images": True,
        "maatlog_generate_feeds": False,
        "maatlog_home_docname": "index",
    }
    config.update(overrides)
    return config


class ExtraProbeGenerator(RecordingGenerator):
    """A RecordingGenerator with caller-chosen probes (test-only)."""

    def __init__(self, probes: Mapping[str, SourceImageProbe]) -> None:
        FakeVariantGenerator.__init__(self, probes)
        self.pids: list[int] = []
        self.probed: list[Path] = []


class PayloadVerifyingGenerator(RecordingGenerator):
    """Re-encode when a cache file exists with unexpected bytes (test-only).

    The shared fake only checks cache existence, so a corrupted payload would
    silently publish garbage. This double verifies the deterministic payload
    and drops corrupt files so the normal generate path re-encodes them.
    """

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        key = compute_variant_key(
            identity=request.identity,
            width=request.width,
            image_format=request.probe.image_format,
            encoder=DEFAULT_ENCODER_PROFILE,
            backend=self.describe_backend(),
        )
        expected = hashlib.sha256(f"{key}:{request.width}".encode("ascii")).digest() * 4
        cache_path = request.cache_root / variant_cache_relpath(key, request.probe.image_format)
        if cache_path.is_file() and cache_path.read_bytes() != expected:
            cache_path.unlink()
        return super().generate(request)


class _FailingEncodeGenerator(RecordingGenerator):
    """A RecordingGenerator whose encoder always fails (test-only)."""

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        del request
        raise ImageProcessingError(Diagnostic(code=IMAGE_ENCODE_FAILED, message="cannot encode in this test"))


class _WarningCapture(logging.Handler):
    """Collect Sphinx log records so a test can assert on a warning (test-only)."""

    def __init__(self, sink: list[logging.LogRecord]) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record)


def _first_build(
    make_sphinx: SphinxFactory,
    generator: RecordingGenerator,
    *,
    files: Mapping[str, str | bytes] | None = None,
    config: Mapping[str, object] | None = None,
) -> Sphinx:
    app = make_sphinx(
        files=files if files is not None else FILES, config=config if config is not None else _base_config()
    )
    register_variant_generator_factory(app, lambda: generator)
    app.connect("html-page-context", record_page_context, priority=900)
    app.build()
    return app


def _rewrite_for_reread(path: Path, content: str | bytes) -> None:
    """Rewrite *path* with a future mtime so Sphinx must re-read its owner.

    Sphinx detects changed sources by mtime alone; two writes in the same
    timestamp tick would look unchanged. Bumping the mtime keeps the test
    deterministic without touching the builder under test.
    """
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    future = time.time_ns() + 2_000_000_000
    os.utime(path, ns=(future, future))


def _codes(error: MaatlogBuildError) -> list[str]:
    return [diagnostic.code for diagnostic in error.diagnostics]


def _assert_generator_idle(generator: RecordingGenerator) -> None:
    """No probe or generate call reached the image backend."""
    assert generator.probed == []
    assert generator.generate_calls == ()


def _output_root(app: Sphinx) -> Path:
    return Path(app.outdir) / str(app.builder.imagedir) / "maatlog"


def _public_state(app: Sphinx) -> dict[str, bytes]:
    root = _output_root(app)
    return {
        path.name: path.read_bytes()
        for path in sorted(root.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


def _manifest_text(app: Sphinx) -> str:
    return (_output_root(app) / ".manifest.json").read_text(encoding="utf-8")


def _manifest_basenames(app: Sphinx) -> set[str]:
    return {variant.public_basename for entry in responsive_manifest(app.env).values() for variant in entry.variants}


def _assert_published_unchanged(app: Sphinx, *, manifest_before: str, state_before: dict[str, bytes]) -> None:
    assert _manifest_text(app) == manifest_before
    assert _public_state(app) == state_before


def _snapshot_dir(app: Sphinx) -> Path:
    return Path(app.outdir) / "_responsive_test"


def _clear_snapshots(app: Sphinx) -> None:
    shutil.rmtree(_snapshot_dir(app), ignore_errors=True)


#: Consumers the build must force-rewrite on every incremental rebuild (post,
#: home, post-list, archive root). The snapshot directory is cleared before
#: each rebuild and one JSON is written per rewritten page, so a page the build
#: fails to rewrite leaves no JSON at all: presence is asserted, not just content.
_REWRITTEN_CONSUMERS: frozenset[str] = frozenset({"posts/one", "index", "listing", "blog"})


def _assert_consumers_rewritten(app: Sphinx) -> None:
    missing = _REWRITTEN_CONSUMERS - set(_snapshot_payloads(app))
    assert not missing, f"consumers missing fresh snapshots (not force-rewritten?): {sorted(missing)}"


def _snapshot_payloads(app: Sphinx) -> dict[str, dict[str, Any]]:
    root = _snapshot_dir(app)
    payloads: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*.json")):
        payloads[path.relative_to(root).with_suffix("").as_posix()] = json.loads(path.read_text(encoding="utf-8"))
    return payloads


def _entry_candidate_urls(entry: Mapping[str, Any] | None, sink: set[str]) -> None:
    if not isinstance(entry, dict):
        return
    url = entry.get("src")
    if isinstance(url, str) and url:
        sink.add(url)
    candidates = entry.get("candidates")
    if isinstance(candidates, (list, tuple)):
        for item in cast(list[Any], candidates):
            if isinstance(item, dict):
                candidate = cast(dict[str, Any], item)
                candidate_url = candidate.get("url")
                if isinstance(candidate_url, str) and candidate_url:
                    sink.add(candidate_url)


def _card_candidates(card: Mapping[str, Any] | None, sink: set[str]) -> None:
    if not isinstance(card, dict):
        return
    _entry_candidate_urls(cast(dict[str, Any] | None, card.get("responsive_image")), sink)


def _card_original(card: Mapping[str, Any] | None, sink: set[str]) -> None:
    if not isinstance(card, dict):
        return
    value = card.get("image_url")
    if isinstance(value, str) and value:
        sink.add(value)


def _snapshot_candidate_urls(payload: Mapping[str, Any]) -> set[str]:
    sink: set[str] = set()
    post = payload.get("post")
    if isinstance(post, dict):
        record = cast(dict[str, Any], post)
        _entry_candidate_urls(cast(dict[str, Any] | None, record.get("responsive_image")), sink)
        _entry_candidate_urls(cast(dict[str, Any] | None, record.get("responsive_top_image")), sink)
    for key in ("posts", "featured", "latest"):
        cards = payload.get(key)
        if isinstance(cards, (list, tuple)):
            for card in cast(list[Any], cards):
                if isinstance(card, dict):
                    _card_candidates(cast(dict[str, Any], card), sink)
    navigation = payload.get("navigation")
    if isinstance(navigation, dict):
        record = cast(dict[str, Any], navigation)
        for key in ("newer_post", "older_post"):
            value = record.get(key)
            if isinstance(value, dict):
                _card_candidates(cast(dict[str, Any], value), sink)
    profile = payload.get("profile")
    if isinstance(profile, dict):
        record = cast(dict[str, Any], profile)
        featured = record.get("featured")
        if isinstance(featured, (list, tuple)):
            for card in cast(list[Any], featured):
                if isinstance(card, dict):
                    _card_candidates(cast(dict[str, Any], card), sink)
    return sink


def _snapshot_original_urls(payload: Mapping[str, Any]) -> set[str]:
    sink: set[str] = set()
    post = payload.get("post")
    if isinstance(post, dict):
        record = cast(dict[str, Any], post)
        for key in ("image_url", "top_image_url"):
            value = record.get(key)
            if isinstance(value, str) and value:
                sink.add(value)
    for key in ("posts", "featured", "latest"):
        cards = payload.get(key)
        if isinstance(cards, (list, tuple)):
            for card in cast(list[Any], cards):
                if isinstance(card, dict):
                    _card_original(cast(dict[str, Any], card), sink)
    navigation = payload.get("navigation")
    if isinstance(navigation, dict):
        record = cast(dict[str, Any], navigation)
        for key in ("newer_post", "older_post"):
            value = record.get(key)
            if isinstance(value, dict):
                _card_original(cast(dict[str, Any], value), sink)
    profile = payload.get("profile")
    if isinstance(profile, dict):
        record = cast(dict[str, Any], profile)
        featured = record.get("featured")
        if isinstance(featured, (list, tuple)):
            for card in cast(list[Any], featured):
                if isinstance(card, dict):
                    _card_original(cast(dict[str, Any], card), sink)
    return sink


def _assert_url_reaches_file(app: Sphinx, pagename: str, url: str) -> None:
    target_uri = app.builder.get_target_uri(pagename)
    joined = urljoin("https://example.test/" + target_uri, url)
    relative = unquote(urlsplit(joined).path.lstrip("/"))
    assert (Path(app.outdir) / relative).is_file(), f"{url} from {pagename} reaches no file"


def _assert_snapshot_candidates_reach(app: Sphinx) -> dict[str, set[str]]:
    payloads = _snapshot_payloads(app)
    assert payloads, "expected fresh page snapshots"
    seen: dict[str, set[str]] = {}
    for pagename, payload in payloads.items():
        urls = _snapshot_candidate_urls(payload) | _snapshot_original_urls(payload)
        for url in sorted(urls):
            _assert_url_reaches_file(app, pagename, url)
        seen[pagename] = urls
    return seen


def _assert_only_references(app: Sphinx, expected_basenames: set[str]) -> set[str]:
    """Every responsive candidate URL in every fresh snapshot names an expected file."""
    payloads = _snapshot_payloads(app)
    assert payloads, "expected fresh page snapshots"
    seen: set[str] = set()
    for payload in payloads.values():
        for url in _snapshot_candidate_urls(payload):
            seen.add(url.rsplit("/", 1)[-1])
    assert seen, "expected responsive candidates in fresh snapshots"
    assert seen <= expected_basenames, f"snapshots reference stale candidates: {sorted(seen - expected_basenames)}"
    return seen


def _rst_with_images(*, slug: str, day: int, image: str | None, maattop: str | None = None) -> str:
    header = f":maatlog-post: true\n:maatlog-slug: {slug}\n:maatlog-published-at: 2026-07-{day:02d}T00:00:00Z\n"
    if image is not None:
        header += f":maatlog-image: {image}\n"
    title = slug.capitalize()
    body = f"\n{title}\n{'=' * len(title)}\n\n"
    if maattop is not None:
        body += f".. maatlog:maattop:: {maattop}\n\n"
    return header + body + "Body.\n"


def test_image_content_change_with_preserved_mtime_updates_manifest(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    before = responsive_manifest(app.env)["img/hero.png"]
    old_names = _manifest_basenames(app)
    old_hero_names = {variant.public_basename for variant in before.variants}
    encodes_before = generator.encode_count
    path = Path(app.srcdir) / "img/hero.png"
    stat = path.stat()
    data = bytearray(path.read_bytes())
    data[-1] ^= 1  # fake probe使用。変更検出の証拠でありPNG decodeの検証ではない
    path.write_bytes(data)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    _clear_snapshots(app)
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    _assert_consumers_rewritten(rebuilt)
    after = responsive_manifest(rebuilt.env)["img/hero.png"]
    assert before.identity.content_hash != after.identity.content_hash
    assert before.variants != after.variants
    assert len(path.read_bytes()) == stat.st_size
    assert generator.encode_count == encodes_before + 5
    new_names = _manifest_basenames(rebuilt)
    assert set(_public_state(rebuilt)) == new_names
    for name in old_hero_names:
        assert not (_output_root(rebuilt) / name).exists()
    seen = _assert_only_references(rebuilt, new_names)
    assert seen == new_names
    _assert_snapshot_candidates_reach(rebuilt)
    assert old_names != new_names


def test_maattop_on_non_post_page_forces_rewrite_on_content_change(make_sphinx: SphinxFactory) -> None:
    files = dict(FILES)
    files["about.rst"] = "About\n=====\n\n.. maatlog:maattop:: img/hero.png\n\nAbout body.\n"
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator, files=files)
    assert "about" in _snapshot_payloads(app)
    old_names = _manifest_basenames(app)
    path = Path(app.srcdir) / "img/hero.png"
    stat = path.stat()
    data = bytearray(path.read_bytes())
    data[-1] ^= 1  # fake probe使用。変更検出の証拠でありPNG decodeの検証ではない
    path.write_bytes(data)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    _clear_snapshots(app)
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    payloads = _snapshot_payloads(rebuilt)
    # ``about`` is neither a post nor a post-list page, so only the
    # ``env-updated`` rewrite instruction can have rewritten it here.
    assert "about" in payloads
    new_names = _manifest_basenames(rebuilt)
    assert old_names != new_names
    seen = _assert_only_references(rebuilt, new_names)
    assert seen == new_names
    _assert_snapshot_candidates_reach(rebuilt)


def test_unchanged_build_reuses_encoded_variants(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    before_state = _public_state(app)
    before_manifest = _manifest_text(app)
    encodes = generator.encode_count
    calls = len(generator.generate_calls)
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    assert generator.encode_count == encodes
    assert len(generator.generate_calls) > calls
    assert _public_state(rebuilt) == before_state
    assert _manifest_text(rebuilt) == before_manifest
    assert dict(responsive_manifest(rebuilt.env)) == dict(responsive_manifest(app.env))
    _assert_snapshot_candidates_reach(rebuilt)


def test_missing_public_file_is_restored(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    before_state = _public_state(app)
    victim = sorted(before_state)[0]
    (_output_root(app) / victim).unlink()
    encodes = generator.encode_count
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    assert generator.encode_count == encodes
    assert _public_state(rebuilt) == before_state


def test_missing_outdir_is_republished(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    before_names = set(_public_state(app))
    shutil.rmtree(Path(app.outdir))
    assert not Path(app.outdir).exists()
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    assert set(_public_state(rebuilt)) == before_names
    assert _manifest_basenames(rebuilt) == before_names
    _assert_snapshot_candidates_reach(rebuilt)
    assert (Path(rebuilt.outdir) / "_images" / "hero.png").is_file()
    assert (Path(rebuilt.outdir) / "_images" / "top.png").is_file()


def test_width_changes_rewrite_all_consumers(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    before_state = _public_state(app)
    old_names = set(before_state)
    assert generator.encode_count == 10
    foreign = _output_root(app) / "keep.png"
    foreign.write_bytes(b"foreign")
    _clear_snapshots(app)
    rebuilt = reopen_build(
        app,
        generator,
        overrides=_base_config(maatlog_responsive_image_widths=(320, 640)),
    )
    assert generator.encode_count == 10 + 4
    new_names = _manifest_basenames(rebuilt)
    assert len(new_names) == 6
    assert set(_public_state(rebuilt)) - {"keep.png"} == new_names
    stale = old_names - new_names
    assert len(stale) == 8
    for name in stale:
        assert not (_output_root(rebuilt) / name).exists()
    after_state = _public_state(rebuilt)
    for name in old_names & new_names:
        assert after_state[name] == before_state[name]
    assert foreign.read_bytes() == b"foreign"
    assert set(json.loads(_manifest_text(rebuilt))["files"]) == new_names
    manifest = responsive_manifest(rebuilt.env)
    assert {variant.width for entry in manifest.values() for variant in entry.variants} == {320, 640, 1600}
    seen = _assert_only_references(rebuilt, new_names)
    assert seen == new_names
    _assert_snapshot_candidates_reach(rebuilt)


def test_on_off_on_preserves_originals(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    assert generator.encode_count == 10
    before_names = set(_public_state(app))
    originals = {
        "_images/hero.png": (Path(app.outdir) / "_images" / "hero.png").read_bytes(),
        "_images/top.png": (Path(app.outdir) / "_images" / "top.png").read_bytes(),
    }
    _clear_snapshots(app)
    off_generator = RecordingGenerator()
    off = reopen_build(
        app,
        off_generator,
        overrides={"maatlog_responsive_images": False, "maatlog_generate_feeds": False},
    )
    _assert_generator_idle(off_generator)
    _assert_consumers_rewritten(off)
    assert responsive_manifest(off.env) == {}
    assert _public_state(off) == {}
    assert json.loads(_manifest_text(off))["files"] == {}
    for relative, data in originals.items():
        assert (Path(off.outdir) / relative).read_bytes() == data
    off_payloads = _snapshot_payloads(off)
    assert off_payloads, "expected rewritten page snapshots on an OFF build"
    for pagename, payload in off_payloads.items():
        assert _snapshot_candidate_urls(payload) == set(), pagename
    post = off_payloads["posts/one"]["post"]
    assert post is not None
    assert post["responsive_image"] is None
    assert post["responsive_top_image"] is None
    _clear_snapshots(off)
    on_generator = RecordingGenerator()
    on = reopen_build(off, on_generator, overrides=_base_config())
    _assert_consumers_rewritten(on)
    assert on_generator.encode_count == 0
    assert set(_public_state(on)) == before_names
    assert _manifest_basenames(on) == before_names
    seen = _assert_only_references(on, before_names)
    assert seen == before_names
    for relative, data in originals.items():
        assert (Path(on.outdir) / relative).read_bytes() == data
    _assert_snapshot_candidates_reach(on)


def _replacement_files(*, one_image: str, two_image: str) -> dict[str, str | bytes]:
    return {
        "posts/one.rst": _rst_with_images(slug="one", day=1, image=one_image, maattop="../img/top.png"),
        "posts/two.rst": _rst_with_images(slug="two", day=2, image=two_image),
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
        "img/hero.png": make_test_png(1600, 900),
        "img/top.png": make_test_png(1600, 900),
    }


def test_source_replacement_removes_unused_variants(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(
        make_sphinx,
        generator,
        files=_replacement_files(one_image="../img/hero.png", two_image="../img/hero.png"),
    )
    hero_names = {variant.public_basename for variant in responsive_manifest(app.env)["img/hero.png"].variants}
    top_names = {variant.public_basename for variant in responsive_manifest(app.env)["img/top.png"].variants}
    assert generator.encode_count == 10
    _rewrite_for_reread(
        Path(app.srcdir) / "posts" / "one.rst",
        _rst_with_images(slug="one", day=1, image="../img/top.png", maattop="../img/top.png"),
    )
    _clear_snapshots(app)
    shared = reopen_build(app, generator, overrides=_base_config())
    assert set(responsive_manifest(shared.env)) == {"img/hero.png", "img/top.png"}
    for name in hero_names | top_names:
        assert (_output_root(shared) / name).is_file()
    assert generator.encode_count == 10
    _rewrite_for_reread(
        Path(app.srcdir) / "posts" / "two.rst",
        _rst_with_images(slug="two", day=2, image="../img/top.png"),
    )
    _clear_snapshots(shared)
    final = reopen_build(shared, generator, overrides=_base_config())
    assert set(responsive_manifest(final.env)) == {"img/top.png"}
    for name in hero_names:
        assert not (_output_root(final) / name).exists()
    for name in top_names:
        assert (_output_root(final) / name).is_file()
    seen = _assert_only_references(final, top_names)
    assert seen == top_names
    _assert_snapshot_candidates_reach(final)


def _removal_files() -> dict[str, str | bytes]:
    return {
        "index.rst": "Home\n====\n\n.. toctree::\n\n   posts/one\n   posts/two\n   listing\n",
        "posts/one.rst": _rst_with_images(slug="one", day=1, image="../img/hero.png", maattop="../img/top.png"),
        "posts/two.rst": _rst_with_images(slug="two", day=2, image="../img/shared.png"),
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
        "img/hero.png": make_test_png(1600, 900),
        "img/top.png": make_test_png(1600, 900),
        "img/shared.png": make_test_png(1600, 900),
    }


def test_removed_post_drops_only_its_sources(make_sphinx: SphinxFactory) -> None:
    generator = ExtraProbeGenerator({"hero.png": PROBE, "top.png": PROBE, "shared.png": PROBE})
    app = _first_build(make_sphinx, generator, files=_removal_files())
    manifest = responsive_manifest(app.env)
    assert set(manifest) == {"img/hero.png", "img/top.png", "img/shared.png"}
    dropped = {
        variant.public_basename for key in ("img/hero.png", "img/top.png") for variant in manifest[key].variants
    }
    kept = {variant.public_basename for variant in manifest["img/shared.png"].variants}
    assert generator.encode_count == 15
    (Path(app.srcdir) / "posts" / "one.rst").unlink()
    _rewrite_for_reread(Path(app.srcdir) / "index.rst", "Home\n====\n\n.. toctree::\n\n   posts/two\n   listing\n")
    _clear_snapshots(app)
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    assert set(responsive_manifest(rebuilt.env)) == {"img/shared.png"}
    assert set(_public_state(rebuilt)) == kept
    for name in dropped:
        assert not (_output_root(rebuilt) / name).exists()
    payloads = _snapshot_payloads(rebuilt)
    assert payloads
    assert "posts/one" not in payloads
    all_urls: set[str] = set()
    for payload in payloads.values():
        all_urls |= _snapshot_candidate_urls(payload) | _snapshot_original_urls(payload)
    assert all_urls, "expected surviving post snapshots"
    assert not any("hero" in url or "top" in url for url in all_urls)
    assert any("shared" in url for url in all_urls)
    _assert_snapshot_candidates_reach(rebuilt)


def test_missing_referenced_source_fails_without_cleanup(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    manifest_before = _manifest_text(app)
    state_before = _public_state(app)
    (Path(app.srcdir) / "img" / "hero.png").unlink()
    fresh = RecordingGenerator()
    with pytest.raises(MaatlogBuildError) as excinfo:
        reopen_build(app, fresh, overrides=_base_config())
    assert _codes(excinfo.value) == [IMAGE_MISSING]
    _assert_generator_idle(fresh)
    _assert_published_unchanged(app, manifest_before=manifest_before, state_before=state_before)


def test_cached_source_replaced_with_symlink_is_rejected(make_sphinx: SphinxFactory, tmp_path: Path) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    manifest_before = _manifest_text(app)
    state_before = _public_state(app)
    hero = Path(app.srcdir) / "img" / "hero.png"
    hero.unlink()
    hero.symlink_to("top.png")
    internal = RecordingGenerator()
    with pytest.raises(MaatlogBuildError) as excinfo:
        reopen_build(app, internal, overrides=_base_config())
    assert _codes(excinfo.value) == [IMAGE_INVALID]
    _assert_generator_idle(internal)
    _assert_published_unchanged(app, manifest_before=manifest_before, state_before=state_before)
    outside = tmp_path / "outside.png"
    outside.write_bytes(make_test_png(1600, 900))
    hero.unlink()
    hero.symlink_to(outside)
    external = RecordingGenerator()
    with pytest.raises(MaatlogBuildError) as external_error:
        reopen_build(app, external, overrides=_base_config())
    assert _codes(external_error.value) == [IMAGE_INVALID]
    _assert_generator_idle(external)
    _assert_published_unchanged(app, manifest_before=manifest_before, state_before=state_before)


def _cache_files(app: Sphinx) -> list[Path]:
    return sorted(path for path in (Path(app.doctreedir) / "maatlog_responsive_images").rglob("*") if path.is_file())


def test_cache_missing_is_regenerated(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    cache_files = _cache_files(app)
    assert len(cache_files) == 10
    cache_files[0].unlink()
    encodes = generator.encode_count
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    assert generator.encode_count == encodes + 1
    assert cache_files[0].is_file()
    assert set(_public_state(rebuilt)) == _manifest_basenames(rebuilt)
    _assert_snapshot_candidates_reach(rebuilt)


def test_corrupt_cache_is_repaired_through_generator(make_sphinx: SphinxFactory) -> None:
    generator = PayloadVerifyingGenerator()
    app = _first_build(make_sphinx, generator)
    cache_files = _cache_files(app)
    assert len(cache_files) == 10
    victim = cache_files[0]
    good = victim.read_bytes()
    victim.write_bytes(bytes(len(good)))
    assert victim.read_bytes() != good
    encodes = generator.encode_count
    rebuilt = reopen_build(app, generator, overrides=_base_config())
    assert generator.encode_count == encodes + 1
    assert victim.read_bytes() == good
    assert set(_public_state(rebuilt)) == _manifest_basenames(rebuilt)
    _assert_snapshot_candidates_reach(rebuilt)


def test_maattop_invalid_uri_warns_and_excludes_at_parse(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    files = {
        "posts/one.md": (
            "---\nmaatlog-post: true\nmaatlog-slug: one\n"
            "maatlog-published-at: 2026-07-01T00:00:00Z\n"
            "maatlog-image: ../img/hero.png\n"
            "maatlog-top-image: ../img/gone.png\n"
            "---\n# One\n\nBody.\n"
        ),
        "img/hero.png": make_test_png(1600, 900),
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
    }
    app = make_sphinx(files=files, config=_base_config())
    register_variant_generator_factory(app, lambda: generator)
    app.connect("html-page-context", record_page_context, priority=900)
    records: list[logging.LogRecord] = []
    capture = _WarningCapture(records)
    logger = logging.getLogger(SPHINX_LOG_NAMESPACE)
    logger.addHandler(capture)
    try:
        app.build()
    finally:
        logger.removeHandler(capture)
    assert any(getattr(record, "subtype", None) == "maattop.invalid-uri" for record in records)
    assert app.statuscode == 1
    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    assert domain.maattop_for("posts/one") is None
    assert set(responsive_manifest(app.env)) == {"img/hero.png"}
    payload = _snapshot_payloads(app)["posts/one"]
    assert payload["post"] is not None
    assert payload["post"]["responsive_top_image"] is None
    assert payload["post"]["responsive_image"] is not None


def test_maattop_stale_record_fails_parent_prepare(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    files = {
        "posts/one.rst": _rst_with_images(slug="one", day=1, image=None, maattop="../img/top.png"),
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
        "img/hero.png": make_test_png(1600, 900),
        "img/top.png": make_test_png(1600, 900),
    }
    app = _first_build(make_sphinx, generator, files=files)
    assert set(responsive_manifest(app.env)) == {"img/top.png"}
    hero = Path(app.srcdir) / "img" / "hero.png"
    top = Path(app.srcdir) / "img" / "top.png"
    aged = hero.stat().st_mtime_ns - 120_000_000_000
    os.utime(hero, ns=(aged, aged))
    top.unlink()
    top.symlink_to("hero.png")
    manifest_before = _manifest_text(app)
    state_before = _public_state(app)
    fresh = RecordingGenerator()
    with pytest.raises(MaatlogBuildError) as excinfo:
        reopen_build(app, fresh, overrides=_base_config())
    assert _codes(excinfo.value) == [IMAGE_INVALID]
    _assert_generator_idle(fresh)
    _assert_published_unchanged(app, manifest_before=manifest_before, state_before=state_before)


def _feed_files() -> dict[str, str | bytes]:
    return {
        "posts/one.rst": (
            ":maatlog-post: true\n:maatlog-slug: one\n"
            ":maatlog-published-at: 2026-07-01T00:00:00Z\n"
            ":maatlog-image: ../img/hero.png\n:maatlog-authors: alice\n"
            "\nOne\n===\n\n.. maatlog:maattop:: ../img/top.png\n\nBody with an inline image.\n\n"
            ".. image:: ../img/inline.png\n"
        ),
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
        "img/hero.png": make_test_png(1600, 900),
        "img/top.png": make_test_png(1600, 900),
        "img/inline.png": make_test_png(800, 600),
    }


def test_feeds_enabled_preserves_shared_originals(make_sphinx: SphinxFactory) -> None:
    generator = ExtraProbeGenerator({"hero.png": PROBE, "top.png": PROBE, "inline.png": PROBE})
    config = _base_config(
        maatlog_generate_feeds=True,
        maatlog_authors={"alice": "Alice"},
        maatlog_author_profiles={"alice": {"avatar": "img/hero.png"}},
    )
    app = _first_build(make_sphinx, generator, files=_feed_files(), config=config)
    overrides = dict(config)
    feed_before = (Path(app.outdir) / "blog" / "atom.xml").read_bytes()
    assert b"<entry" in feed_before
    post_html_before = (Path(app.outdir) / "posts" / "one.html").read_text(encoding="utf-8")
    assert 'property="og:image" content="https://example.test/_images/hero.png"' in post_html_before
    originals_before = {
        name: (Path(app.outdir) / "_images" / name).read_bytes() for name in ("hero.png", "top.png", "inline.png")
    }
    rebuilt = reopen_build(app, generator, overrides=overrides)
    assert (Path(rebuilt.outdir) / "blog" / "atom.xml").read_bytes() == feed_before
    post_html_after = (Path(rebuilt.outdir) / "posts" / "one.html").read_text(encoding="utf-8")
    assert 'property="og:image" content="https://example.test/_images/hero.png"' in post_html_after
    for name, data in originals_before.items():
        assert (Path(rebuilt.outdir) / "_images" / name).read_bytes() == data
    assert set(responsive_manifest(rebuilt.env)) == {"img/hero.png", "img/top.png"}
    _assert_snapshot_candidates_reach(rebuilt)


def test_backend_failure_on_rebuild_keeps_owned_variants(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    names_before = set(_public_state(app))
    manifest_before = _manifest_text(app)
    state_before = _public_state(app)
    with pytest.raises(MaatlogBuildError) as excinfo:
        reopen_build(app, _FailingEncodeGenerator(), overrides=_base_config())
    assert _codes(excinfo.value) == [IMAGE_ENCODE_FAILED]
    _assert_published_unchanged(app, manifest_before=manifest_before, state_before=state_before)
    retry_generator = RecordingGenerator()
    retry = reopen_build(app, retry_generator, overrides=_base_config())
    assert retry_generator.encode_count == 0
    assert set(_public_state(retry)) == names_before
    assert _manifest_text(retry) == manifest_before
    _assert_snapshot_candidates_reach(retry)


def test_writer_failure_on_rebuild_keeps_owned_variants(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = _first_build(make_sphinx, generator)
    names_before = set(_public_state(app))
    manifest_before = _manifest_text(app)
    state_before = _public_state(app)
    failing = _new_app(app, _base_config())
    fail_generator = RecordingGenerator()
    register_variant_generator_factory(failing, lambda: fail_generator)
    failing.connect("html-page-context", record_page_context, priority=900)

    def _boom(app_inner: Sphinx, builder: SphinxBuilder) -> None:
        del app_inner, builder
        raise RuntimeError("simulated writer failure")

    failing.connect("write-started", _boom, priority=450)
    with pytest.raises(ExtensionError, match="simulated writer failure") as excinfo:
        failing.build()
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    _assert_published_unchanged(app, manifest_before=manifest_before, state_before=state_before)
    retry = reopen_build(app, RecordingGenerator(), overrides=_base_config())
    assert set(_public_state(retry)) == names_before
    _assert_snapshot_candidates_reach(retry)

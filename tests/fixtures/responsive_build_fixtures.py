"""C-dedicated responsive-image build doubles for issue #215 (lane C, parent #207).

Consumes the frozen shared doubles without changing them: the fake payload
bytes are never decoded, and geometry always comes from the declared probe.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from io import StringIO
from pathlib import Path
from typing import Any, cast

from fixtures.responsive_image_fixtures import FAKE_BACKEND, FakeVariantGenerator, make_test_png
from sphinx.application import Sphinx

from maatlog.image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    BackendInfo,
    GeneratedVariant,
    ImageFormat,
    ImageVariantGenerator,
    SourceImageIdentity,
    SourceImageProbe,
    VariantRequest,
    compute_variant_key,
    register_variant_generator_factory,
    scaled_height,
    variant_cache_relpath,
    variant_public_basename,
)
from maatlog.responsive_image_output import commit_owned_variants, publish_variants

PROBE = SourceImageProbe(
    image_format=ImageFormat.PNG,
    width=1600,
    height=900,
    is_multi_frame=False,
    has_alpha=True,
)


class RecordingGenerator(FakeVariantGenerator):
    def __init__(self) -> None:
        super().__init__({"hero.png": PROBE, "top.png": PROBE})
        self.pids: list[int] = []
        self.probed: list[Path] = []
        #: Opt-in cross-process PID log (test-only). When set, every probe and
        #: generate call appends its PID, so generation inside a forked worker
        #: stays visible to the parent. ``None`` keeps existing behavior.
        self.pid_log: Path | None = None

    def _record_pid(self) -> None:
        pid = os.getpid()
        self.pids.append(pid)
        # getattr: subclasses that bypass this __init__ never set pid_log.
        pid_log = getattr(self, "pid_log", None)
        if pid_log is not None:
            with pid_log.open("a", encoding="utf-8") as stream:
                stream.write(f"{pid}\n")

    def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        self._record_pid()
        self.probed.append(source_path)
        return super().probe(source_path, image_format=image_format)

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        self._record_pid()
        return super().generate(request)


def _new_app(
    previous: Sphinx,
    overrides: Mapping[str, object] | None = None,
    parallel: int = 0,
) -> Sphinx:
    """Create (but do not build) the incremental second app (test-only).

    Split from :func:`reopen_build` so tests that attach extra hooks before
    building share the exact construction instead of copying it.
    """
    return Sphinx(
        str(previous.srcdir),
        str(previous.confdir),
        str(previous.outdir),
        str(previous.doctreedir),
        previous.builder.name,
        confoverrides=dict(overrides or {}),
        freshenv=False,
        parallel=parallel,
        status=StringIO(),
        warning=StringIO(),
        warningiserror=True,
    )


def reopen_build(
    previous: Sphinx,
    generator: ImageVariantGenerator | None,
    *,
    overrides: Mapping[str, object] | None = None,
    parallel: int = 0,
) -> Sphinx:
    """Rebuild the same project incrementally with a second Sphinx app (test-only).

    Reuses ``previous`` srcdir/confdir/outdir/doctreedir with ``freshenv=False``
    so Sphinx itself decides what is stale; never ``force_all=True``. The
    previous app's ``confoverrides`` do not persist to ``conf.py``, so every
    intended setting must be passed via *overrides* on every rebuild. The
    generator factory and the page-context recorder are re-registered because
    connections belong to the old app, not the directories.
    """
    app = _new_app(previous, overrides, parallel)
    if generator is not None:
        register_variant_generator_factory(app, lambda: generator)
    app.connect("html-page-context", record_page_context, priority=900)
    app.build()
    return app


FILES: dict[str, str | bytes] = {
    "posts/one.rst": ":maatlog-post: true\n:maatlog-slug: one\n"
    ":maatlog-published-at: 2026-07-01T00:00:00Z\n"
    ":maatlog-image: ../img/hero.png\n\nOne\n===\n\n"
    ".. maatlog:maattop:: ../img/top.png\n\nBody.\n",
    "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
    "img/hero.png": make_test_png(1600, 900),
    "img/top.png": make_test_png(1600, 900),
}


def _responsive_entry_json(entry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """JSON-safe projection of one responsive entry mapping (test-only)."""
    if not isinstance(entry, dict):
        return None
    candidates = entry.get("candidates")
    safe_candidates: list[dict[str, Any]] = []
    if isinstance(candidates, (list, tuple)):
        candidate_list = cast(list[Any], candidates)
        for candidate in candidate_list:
            if isinstance(candidate, dict):
                candidate_map = cast(dict[str, Any], candidate)
                safe_candidates.append({"url": candidate_map.get("url"), "width": candidate_map.get("width")})
    usage = entry.get("usage")
    return {
        "src": entry.get("src"),
        "srcset": entry.get("srcset"),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "usage": str(usage) if usage is not None else None,
        "candidates": safe_candidates,
    }


def _card_json(card: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        return None
    return {
        "slug": card.get("slug"),
        "image_url": card.get("image_url"),
        "responsive_image": _responsive_entry_json(card.get("responsive_image")),
    }


def _cards_json(cards: Sequence[Any] | None) -> list[dict[str, Any]]:
    if not isinstance(cards, (list, tuple)):
        return []
    return [item for item in (_card_json(card) for card in cards) if item is not None]


def record_page_context(
    app: Any, pagename: str, templatename: str, context: Mapping[str, Any] | None, doctree: Any
) -> None:
    """Persist image-related ``maatlog`` fields for one page (test-only).

    Connected at ``html-page-context`` priority 900. Each worker writes only
    its own pagename file under ``<outdir>/_responsive_test/``; nothing is
    appended to a shared list, so parallel workers never contend.
    """
    del templatename, doctree
    if not isinstance(context, dict):
        return
    maatlog = cast(dict[str, Any] | None, context.get("maatlog"))
    if not isinstance(maatlog, dict):
        return
    post = cast(dict[str, Any] | None, maatlog.get("post"))
    post_json: dict[str, Any] | None = None
    if isinstance(post, dict):
        post_json = {
            "slug": post.get("slug"),
            "image_url": post.get("image_url"),
            "top_image_url": post.get("top_image_url"),
            "responsive_image": _responsive_entry_json(post.get("responsive_image")),
            "responsive_top_image": _responsive_entry_json(post.get("responsive_top_image")),
        }
    navigation = cast(dict[str, Any] | None, maatlog.get("navigation"))
    navigation_json: dict[str, Any] = {"newer_post": None, "older_post": None}
    if isinstance(navigation, dict):
        navigation_json = {
            "newer_post": _card_json(navigation.get("newer_post")),
            "older_post": _card_json(navigation.get("older_post")),
        }
    profile = cast(dict[str, Any] | None, maatlog.get("profile"))
    profile_json: dict[str, Any] | None = None
    if isinstance(profile, dict):
        profile_json = {"featured": _cards_json(profile.get("featured"))}
    payload = {
        "pagename": pagename,
        "post": post_json,
        "posts": _cards_json(maatlog.get("posts")),
        "featured": _cards_json(maatlog.get("featured")),
        "latest": _cards_json(maatlog.get("latest")),
        "navigation": navigation_json,
        "profile": profile_json,
    }
    output_path = Path(app.outdir) / "_responsive_test" / f"{pagename}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def parallel_files() -> dict[str, str | bytes]:
    """Parallel-build fixture: T1 ``FILES`` plus eight extra posts (test-only).

    Every extra post references the same hero/top sources with a unique slug
    and date, so the Sphinx writer-parallel branch has enough pages to fan out
    to workers while the manifest stays at two sources.
    """
    files = dict(FILES)
    for index in range(8):
        title = f"Parallel {index}"
        files[f"posts/parallel-{index}.rst"] = (
            ":maatlog-post: true\n"
            f":maatlog-slug: parallel-{index}\n"
            f":maatlog-published-at: 2026-07-{index + 2:02d}T00:00:00Z\n"
            ":maatlog-image: ../img/hero.png\n\n"
            f"{title}\n{'=' * len(title)}\n\n"
            ".. maatlog:maattop:: ../img/top.png\n\nBody.\n"
        )
    return files


class AtomicTestGenerator:
    """Process-safe variant double for the shared-cache test (test-only).

    Uses lane A's key function and the shared fake's deterministic payload, but
    every cache miss writes through a unique temporary file and an atomic
    replace, so two OS processes racing on one cache root never observe a
    partial file. An intact cache file is reused without rewriting. The cache
    root is never deleted, and the process id appears only in logs, never in
    payloads or names.

    This double is evidence of lane C's copy/cache coordination, not a
    replacement for lane B's parallel-encoding tests.
    """

    def __init__(
        self, probes: Mapping[str, SourceImageProbe] | None = None, *, backend: BackendInfo | None = None
    ) -> None:
        self._probes = dict(probes) if probes is not None else {"hero.png": PROBE, "top.png": PROBE}
        self._backend = backend if backend is not None else FAKE_BACKEND

    def describe_backend(self) -> BackendInfo:
        return self._backend

    def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        del image_format
        return self._probes[source_path.name]

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        if request.width > request.probe.width:
            raise ValueError("refusing to upscale a responsive image variant")
        key = compute_variant_key(
            identity=request.identity,
            width=request.width,
            image_format=request.probe.image_format,
            encoder=DEFAULT_ENCODER_PROFILE,
            backend=self._backend,
        )
        cache_path = request.cache_root / variant_cache_relpath(key, request.probe.image_format)
        payload = hashlib.sha256(f"{key}:{request.width}".encode("ascii")).digest() * 4
        if not cache_path.is_file() or cache_path.read_bytes() != payload:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=cache_path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload)
                os.replace(temporary, cache_path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return GeneratedVariant(
            width=request.width,
            height=scaled_height(
                natural_width=request.probe.width,
                natural_height=request.probe.height,
                target_width=request.width,
            ),
            image_format=request.probe.image_format,
            cache_path=cache_path,
            public_basename=variant_public_basename(
                identity=request.identity,
                key=key,
                width=request.width,
                image_format=request.probe.image_format,
            ),
            byte_size=cache_path.stat().st_size,
        )


_DRIVER_WIDTHS: tuple[int, ...] = (480, 768, 960, 1200, 1600)

_DRIVER_SOURCES: tuple[tuple[str, tuple[int, int, int, int]], ...] = (
    ("img/hero.png", (32, 64, 128, 255)),
    ("img/top.png", (16, 32, 48, 255)),
)


def _driver_requests(cache_root: Path) -> list[VariantRequest]:
    """Identical variant requests for every driver process (test-only).

    Both drivers use the same source bytes, relative identities, and widths,
    so shared cache entries and published bytes must match exactly.
    """
    requests: list[VariantRequest] = []
    for relpath, rgba in _DRIVER_SOURCES:
        source_bytes = make_test_png(1600, 900, rgba=rgba)
        identity = SourceImageIdentity(
            source_relpath=relpath,
            content_hash=hashlib.sha256(source_bytes).hexdigest(),
        )
        probe = SourceImageProbe(
            image_format=ImageFormat.PNG,
            width=1600,
            height=900,
            is_multi_frame=False,
            has_alpha=True,
        )
        for width in _DRIVER_WIDTHS:
            requests.append(
                VariantRequest(
                    source_path=Path(relpath),
                    identity=identity,
                    probe=probe,
                    width=width,
                    cache_root=cache_root,
                )
            )
    return requests


def run_shared_cache_driver(argv: Sequence[str]) -> int:
    """Run one OS-process shared-cache driver (test-only).

    Usage: ``python responsive_build_fixtures.py <cache_root> <output_root>
    <builder_name>``. Generates every driver variant, publishes it to
    *output_root* from the shared *cache_root* through the adapter publication
    path, and records ownership under *builder_name*. Prints the process id and
    counts to stdout for the parent test to log.
    """
    if len(argv) != 3:
        print(
            "usage: responsive_build_fixtures.py <cache_root> <output_root> <builder_name>",
            file=sys.stderr,
        )
        return 2
    cache_root = Path(argv[0])
    output_root = Path(argv[1])
    builder_name = argv[2]
    generator = AtomicTestGenerator()
    variants = [generator.generate(request) for request in _driver_requests(cache_root)]
    current = publish_variants(variants, cache_root=cache_root, output_root=output_root)
    commit_owned_variants(output_root=output_root, builder_name=builder_name, current=current)
    print(f"shared-cache-driver pid={os.getpid()} variants={len(variants)} files={len(current)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_shared_cache_driver(sys.argv[1:]))

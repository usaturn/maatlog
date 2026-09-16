from __future__ import annotations

import hashlib
import json
import os
import pickle
from collections.abc import Mapping
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from conftest import SphinxFactory
from fixtures.responsive_build_fixtures import FILES, PROBE, RecordingGenerator, record_page_context
from fixtures.responsive_image_fixtures import (
    FAKE_BACKEND,
    GIF_BYTES,
    JPEG_HEADER_BYTES,
    SVG_BYTES,
    WEBP_HEADER_BYTES,
    FakeVariantGenerator,
    make_test_png,
)
from sphinx.application import Sphinx
from sphinx.builders import Builder as SphinxBuilder

from maatlog.errors import Diagnostic, MaatlogBuildError
from maatlog.image_contracts import (
    IMAGE_BACKEND_MISSING,
    IMAGE_CACHE_UNWRITABLE,
    IMAGE_CODEC_MISSING,
    IMAGE_DECODE_FAILED,
    IMAGE_ENCODE_FAILED,
    IMAGE_TOO_LARGE,
    BackendInfo,
    GeneratedVariant,
    ImageFormat,
    ImageProcessingError,
    SourceImageProbe,
    VariantRequest,
    register_variant_generator_factory,
)
from maatlog.responsive_image_build import (
    finish_responsive_images,
    prepare_responsive_images,
    responsive_manifest,
)
from maatlog.responsive_image_output import IMAGE_INVALID_VARIANT
from maatlog.responsive_images import PillowImageVariantGenerator

MULTIFRAME_PROBE = SourceImageProbe(
    image_format=ImageFormat.PNG,
    width=1600,
    height=900,
    is_multi_frame=True,
    has_alpha=True,
)

JPEG_PROBE = SourceImageProbe(
    image_format=ImageFormat.JPEG,
    width=1600,
    height=900,
    is_multi_frame=False,
    has_alpha=False,
)


class CustomRecordingGenerator(RecordingGenerator):
    """A RecordingGenerator with caller-chosen probes for fallback tests."""

    def __init__(self, probes: dict[str, SourceImageProbe], *, backend: BackendInfo | None = None) -> None:
        FakeVariantGenerator.__init__(self, probes, backend=backend)
        self.pids: list[int] = []
        self.probed: list[Path] = []


def _post_with_image(image: str, *, maattop: str | None = None) -> str:
    top = f"\n.. maatlog:maattop:: {maattop}\n" if maattop is not None else ""
    return (
        ":maatlog-post: true\n:maatlog-slug: one\n"
        ":maatlog-published-at: 2026-07-01T00:00:00Z\n"
        f":maatlog-image: {image}\n\nOne\n===\n{top}\nBody.\n"
    )


def test_parent_builds_one_manifest_entry_per_source(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    manifest = responsive_manifest(app.env)
    assert set(manifest) == {"img/hero.png", "img/top.png"}
    assert tuple(v.width for v in manifest["img/hero.png"].variants) == (480, 768, 960, 1200, 1600)
    assert len(generator.probed) == 2
    assert set(generator.pids) == {os.getpid()}
    assert pickle.loads(pickle.dumps(dict(manifest))) == dict(manifest)


def test_prepare_returns_maattop_owners_for_rewrite(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    assert prepare_responsive_images(app, app.env) == ["posts/one"]


def test_disabled_build_resolves_no_backend_and_computes_nothing(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not be called on a disabled build")

    monkeypatch.setattr("maatlog.responsive_image_build.build_source_identity", fail)
    monkeypatch.setattr("maatlog.responsive_image_build.sniff_source_format", fail)
    monkeypatch.setattr("maatlog.responsive_image_build.select_candidate_widths", fail)
    constructed: list[int] = []

    def factory() -> RecordingGenerator:
        constructed.append(1)
        raise AssertionError("factory must not be called on a disabled build")

    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": False})
    register_variant_generator_factory(app, factory)
    app.build()
    assert constructed == []
    assert responsive_manifest(app.env) == {}


@pytest.mark.parametrize("builder", ["text", "singlehtml"])
def test_enabled_non_full_html_builders_generate_nothing(make_sphinx: SphinxFactory, builder: str) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True}, builder=builder)
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    assert generator.probed == []
    assert generator.generate_calls == ()
    assert responsive_manifest(app.env) == {}
    assert [path for path in Path(app.outdir).rglob("maatlog")] == []


def test_enabled_with_unavailable_backend_fails_with_backend_missing(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(self: PillowImageVariantGenerator) -> None:
        raise ImageProcessingError(
            Diagnostic(
                code=IMAGE_BACKEND_MISSING,
                message="Backend unavailable in this boundary test",
                expected='pip install "maatlog[images]"',
            )
        )

    monkeypatch.setattr(PillowImageVariantGenerator, "describe_backend", unavailable)
    with pytest.raises(MaatlogBuildError) as error:
        app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
        app.build()
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == IMAGE_BACKEND_MISSING
    assert "maatlog[images]" in (diagnostic.expected or "")


def test_describe_backend_failure_keeps_its_diagnostic(make_sphinx: SphinxFactory) -> None:
    diagnostic = Diagnostic(
        code=IMAGE_BACKEND_MISSING,
        message="No usable image backend is installed",
        expected='Pillow installed via: pip install "maatlog[images]"',
    )

    class BrokenBackend(CustomRecordingGenerator):
        def describe_backend(self) -> BackendInfo:
            raise ImageProcessingError(diagnostic)

    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: BrokenBackend({"hero.png": PROBE, "top.png": PROBE}))
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert error.value.diagnostics[0].code == IMAGE_BACKEND_MISSING
    assert error.value.diagnostics[0].message == "No usable image backend is installed"
    assert responsive_manifest(app.env) == {}
    assert not (Path(app.outdir) / "posts" / "one.html").exists()


def test_unsupported_formats_publish_the_original_without_backend_calls(make_sphinx: SphinxFactory) -> None:
    files = {
        "posts/one.rst": _post_with_image("../img/hero.gif", maattop="../img/top.svg"),
        "img/hero.gif": GIF_BYTES,
        "img/top.svg": SVG_BYTES,
    }
    generator = CustomRecordingGenerator({"hero.gif": PROBE, "top.svg": PROBE})
    app = make_sphinx(files=files, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    assert generator.probed == []
    assert generator.generate_calls == ()
    assert responsive_manifest(app.env) == {}
    assert "img/hero.gif" in app.builder.images
    assert "img/top.svg" in app.builder.images
    assert (Path(app.outdir) / "_images" / "hero.gif").is_file()
    assert (Path(app.outdir) / "_images" / "top.svg").is_file()


def test_animated_source_leaves_no_manifest_entry(make_sphinx: SphinxFactory) -> None:
    files = {
        "posts/one.rst": _post_with_image("../img/hero.png"),
        "img/hero.png": make_test_png(1600, 900),
    }
    generator = CustomRecordingGenerator({"hero.png": MULTIFRAME_PROBE})
    app = make_sphinx(files=files, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    assert len(generator.probed) == 1
    assert generator.generate_calls == ()
    assert responsive_manifest(app.env) == {}


def test_source_format_follows_content_not_extension(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        "posts/one.rst": _post_with_image("../img/photo.png"),
        "img/photo.png": JPEG_HEADER_BYTES + bytes(128),
    }
    generator = CustomRecordingGenerator({"photo.png": JPEG_PROBE})
    seen: list[ImageFormat] = []
    original_probe = generator.probe

    def probe_spy(source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        seen.append(image_format)
        return original_probe(source_path, image_format=image_format)

    monkeypatch.setattr(generator, "probe", probe_spy)
    app = make_sphinx(files=files, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    manifest = responsive_manifest(app.env)
    assert seen == [ImageFormat.JPEG]
    assert manifest["img/photo.png"].image_format == ImageFormat.JPEG


def test_backend_without_a_matching_codec_fails(make_sphinx: SphinxFactory) -> None:
    generator = CustomRecordingGenerator(
        {"hero.png": PROBE}, backend=replace(FAKE_BACKEND, supported_formats=frozenset())
    )
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert error.value.diagnostics[0].code == IMAGE_CODEC_MISSING
    assert responsive_manifest(app.env) == {}


@pytest.mark.parametrize(
    "code",
    [IMAGE_DECODE_FAILED, IMAGE_TOO_LARGE, IMAGE_ENCODE_FAILED, IMAGE_CACHE_UNWRITABLE],
)
def test_backend_failures_keep_their_code_and_publish_nothing(make_sphinx: SphinxFactory, code: str) -> None:
    diagnostic = Diagnostic(code=code, message=f"backend failed with {code}")

    class FailingGenerator(CustomRecordingGenerator):
        def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
            if code in (IMAGE_DECODE_FAILED, IMAGE_TOO_LARGE) and source_path.name == "top.png":
                raise ImageProcessingError(diagnostic)
            return super().probe(source_path, image_format=image_format)

        def generate(self, request: VariantRequest) -> GeneratedVariant:
            if code in (IMAGE_ENCODE_FAILED, IMAGE_CACHE_UNWRITABLE):
                raise ImageProcessingError(diagnostic)
            return super().generate(request)

    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: FailingGenerator({"hero.png": PROBE, "top.png": PROBE}))
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert error.value.diagnostics[0].code == code
    assert responsive_manifest(app.env) == {}


class _LyingGenerator(RecordingGenerator):
    """A RecordingGenerator that breaks the adapter contract (test-only)."""

    def __init__(self, *, lie: str) -> None:
        super().__init__()
        assert lie in ("width", "format")
        self._lie = lie

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        honest = super().generate(request)
        if self._lie == "width":
            return replace(honest, width=honest.width + 1)
        return replace(honest, image_format=ImageFormat.JPEG)


@pytest.mark.parametrize("lie", ["width", "format"])
def test_contract_violating_variant_fails_with_invalid_variant(make_sphinx: SphinxFactory, lie: str) -> None:
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: _LyingGenerator(lie=lie))
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert responsive_manifest(app.env) == {}
    assert not (Path(app.outdir) / "_images" / "maatlog").exists()


def test_shared_source_is_probed_once_for_all_usages(make_sphinx: SphinxFactory) -> None:
    files = {
        "posts/one.rst": _post_with_image("../img/shared.png", maattop="../img/shared.png"),
        "posts/two.rst": (
            ":maatlog-post: true\n:maatlog-slug: two\n"
            ":maatlog-published-at: 2026-07-02T00:00:00Z\n"
            ":maatlog-image: ../img/shared.png\n\nTwo\n===\n\nBody.\n"
        ),
        "img/shared.png": make_test_png(1600, 900),
    }
    generator = CustomRecordingGenerator({"shared.png": PROBE})
    app = make_sphinx(files=files, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    manifest = responsive_manifest(app.env)
    assert set(manifest) == {"img/shared.png"}
    assert len(generator.probed) == 1
    assert len(generator.generate_calls) == 5


def test_normalized_special_character_paths_resolve_to_the_right_sources(make_sphinx: SphinxFactory) -> None:
    names = ("my photo.png", "a,b.png", "日本語.png", "100%.png")
    files: dict[str, str | bytes] = {}
    for index, name in enumerate(names):
        files[f"posts/p{index}.rst"] = (
            ":maatlog-post: true\n"
            f":maatlog-slug: p{index}\n"
            ":maatlog-published-at: 2026-07-01T00:00:00Z\n"
            f":maatlog-image: ../img/{name}\n\nP{index}\n====\n\nBody.\n"
        )
        files[f"img/{name}"] = make_test_png(1600, 900)
    generator = CustomRecordingGenerator({name: PROBE for name in names})
    app = make_sphinx(files=files, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    manifest = responsive_manifest(app.env)
    assert set(manifest) == {f"img/{name}" for name in names}
    for name in names:
        assert tuple(v.width for v in manifest[f"img/{name}"].variants) == (480, 768, 960, 1200, 1600)
    assert len(generator.probed) == 4


def test_webp_source_generates_webp_variants(make_sphinx: SphinxFactory) -> None:
    webp_probe = SourceImageProbe(
        image_format=ImageFormat.WEBP,
        width=1600,
        height=900,
        is_multi_frame=False,
        has_alpha=False,
    )
    files = {
        "posts/one.rst": _post_with_image("../img/hero.webp"),
        "img/hero.webp": WEBP_HEADER_BYTES + bytes(128),
    }
    generator = CustomRecordingGenerator({"hero.webp": webp_probe})
    app = make_sphinx(files=files, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    manifest = responsive_manifest(app.env)
    assert manifest["img/hero.webp"].image_format == ImageFormat.WEBP
    assert tuple(v.width for v in manifest["img/hero.webp"].variants) == (480, 768, 960, 1200, 1600)


def test_publish_places_candidates_before_writer_callbacks(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    seen_write_started: list[int] = []
    seen_page_context: list[int] = []

    def on_write_started(app_inner: Sphinx, builder: SphinxBuilder) -> None:
        assert isinstance(builder, SphinxBuilder)
        manifest = responsive_manifest(app_inner.env)
        assert manifest
        for entry in manifest.values():
            for variant in entry.variants:
                candidate = Path(builder.outdir) / str(builder.imagedir) / "maatlog" / variant.public_basename
                assert candidate.is_file(), variant.public_basename
        seen_write_started.append(os.getpid())

    def on_page_context(
        app_inner: Sphinx,
        pagename: str,
        templatename: str,
        context: object,
        doctree: object,
    ) -> None:
        del pagename, templatename, context, doctree
        manifest = responsive_manifest(app_inner.env)
        for entry in manifest.values():
            for variant in entry.variants:
                candidate = (
                    Path(app_inner.outdir) / str(app_inner.builder.imagedir) / "maatlog" / variant.public_basename
                )
                assert candidate.is_file(), variant.public_basename
        seen_page_context.append(os.getpid())

    app.connect("write-started", on_write_started, priority=450)
    app.connect("html-page-context", on_page_context)
    app.build()
    assert seen_write_started == [os.getpid()]
    assert seen_page_context
    assert set(generator.pids) == {os.getpid()}
    assert "img/hero.png" in app.builder.images
    assert "img/top.png" in app.builder.images
    assert (Path(app.outdir) / "_images" / "hero.png").is_file()
    assert (Path(app.outdir) / "_images" / "top.png").is_file()
    manifest = responsive_manifest(app.env)
    output_root = Path(app.outdir) / str(app.builder.imagedir) / "maatlog"
    expected: set[str] = set()
    for entry in manifest.values():
        for variant in entry.variants:
            expected.add(variant.public_basename)
            assert (output_root / variant.public_basename).is_file()
    assert len(expected) == 10
    data = json.loads((output_root / ".manifest.json").read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["builder"] == "html"
    assert set(data["files"]) == expected
    for name, digest in data["files"].items():
        assert digest == hashlib.sha256((output_root / name).read_bytes()).hexdigest()


def test_off_first_build_creates_no_output_directory(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": False})
    app.build()
    assert [path for path in Path(app.outdir).rglob("maatlog")] == []
    assert not (Path(app.doctreedir) / "maatlog_responsive_images").exists()


def test_off_cleans_previously_owned_variants(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    output_root = Path(app.outdir) / str(app.builder.imagedir) / "maatlog"
    assert (output_root / ".manifest.json").is_file()
    owned = {path.name for path in output_root.iterdir() if not path.name.startswith(".")}
    assert len(owned) == 10
    foreign = output_root / "keep.png"
    foreign.write_bytes(b"foreign")
    second = Sphinx(
        str(app.srcdir),
        str(app.confdir),
        str(app.outdir),
        str(app.doctreedir),
        app.builder.name,
        confoverrides={"maatlog_responsive_images": False},
        freshenv=False,
        status=StringIO(),
        warning=StringIO(),
        warningiserror=True,
    )
    second.build()
    assert not any((output_root / name).exists() for name in owned)
    assert foreign.read_bytes() == b"foreign"
    assert json.loads((output_root / ".manifest.json").read_text(encoding="utf-8")) == {
        "schema": 1,
        "builder": "html",
        "files": {},
    }


def test_non_html_build_leaves_ownership_untouched(make_sphinx: SphinxFactory, tmp_path: Path) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    output_root = Path(app.outdir) / str(app.builder.imagedir) / "maatlog"
    owned = {path.name: path.read_bytes() for path in output_root.iterdir() if not path.name.startswith(".")}
    assert len(owned) == 10
    manifest_bytes = (output_root / ".manifest.json").read_bytes()
    doctrees_text = tmp_path / "doctrees-text"
    doctrees_text.mkdir()
    text_app = Sphinx(
        str(app.srcdir),
        str(app.confdir),
        str(app.outdir),
        str(doctrees_text),
        "text",
        confoverrides={"maatlog_responsive_images": True},
        freshenv=True,
        status=StringIO(),
        warning=StringIO(),
        warningiserror=True,
    )
    register_variant_generator_factory(text_app, lambda: generator)
    text_app.build()
    assert (output_root / ".manifest.json").read_bytes() == manifest_bytes
    for name, data in owned.items():
        assert (output_root / name).read_bytes() == data


def test_failed_build_keeps_old_manifest_and_files(make_sphinx: SphinxFactory) -> None:
    generator = RecordingGenerator()
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    output_root = Path(app.outdir) / str(app.builder.imagedir) / "maatlog"
    manifest_bytes = (output_root / ".manifest.json").read_bytes()
    first_name = next(iter(json.loads(manifest_bytes.decode("utf-8"))["files"]))
    variant_bytes = (output_root / first_name).read_bytes()
    finish_responsive_images(app, RuntimeError("failed"))
    assert (output_root / ".manifest.json").read_bytes() == manifest_bytes
    assert (output_root / first_name).read_bytes() == variant_bytes


# --- Task 3: view projection across every consumer (test-only snapshot) ---

_POST_CARD_TEST_TEMPLATE = """<article data-test-slug="{{ card.slug|e }}">
{% if card.responsive_image %}
<img data-test-responsive="{{ card.responsive_image.usage|e }}"
     src="{{ card.responsive_image.src|e }}"
     srcset="{{ card.responsive_image.srcset|e }}"
     width="{{ card.responsive_image.width }}" height="{{ card.responsive_image.height }}">
{% elif card.image_url %}<img src="{{ card.image_url|e }}">{% endif %}
</article>
"""


def _rst_post(
    slug: str, *, day: int, image: str | None = None, tags: str = "", authors: str = "", maattop: str | None = None
) -> str:
    lines = [
        ":maatlog-post: true",
        f":maatlog-slug: {slug}",
        f":maatlog-published-at: 2026-07-{day:02d}T09:00:00Z",
    ]
    if image is not None:
        lines.append(f":maatlog-image: {image}")
    if tags:
        lines.append(f":maatlog-tags: {tags}")
    if authors:
        lines.append(f":maatlog-authors: {authors}")
    lines += ["", slug.capitalize(), "=" * len(slug), ""]
    if maattop is not None:
        lines.append(f".. maatlog:maattop:: {maattop}")
        lines.append("")
    lines.append("Body.")
    lines.append("")
    return "\n".join(lines)


def _consumer_files() -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {
        "index.rst": "Home\n====\n\nWelcome.\n",
        "p1.rst": _rst_post("p1", day=6, image="img/p1.png", tags="sphinx", authors="alice", maattop="img/top1.png"),
        "p2.rst": _rst_post("p2", day=5, image="img/p2.png", tags="sphinx", authors="alice"),
        "p3.md": (
            "---\n"
            "maatlog-post: true\n"
            "maatlog-slug: p3\n"
            "maatlog-published-at: 2026-07-04T09:00:00Z\n"
            "maatlog-image: img/p3.png\n"
            "maatlog-tags: [python]\n"
            "maatlog-authors: [bob]\n"
            "maatlog-top-image: img/top3.png\n"
            "maatlog-top-image-alt: Third hero\n"
            "---\n# P3\n\nBody.\n"
        ),
        "p4.rst": _rst_post("p4", day=3, image="img/p4.png", tags="python", authors="bob"),
        "p5.rst": _rst_post("p5", day=2, image="img/p5.png", tags="sphinx", authors="bob"),
        "p6.rst": _rst_post("p6", day=1, image=None, tags="sphinx", authors="alice"),
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
        "_templates/maatlog/components/post-card.html": _POST_CARD_TEST_TEMPLATE,
        "img/p1.png": make_test_png(1600, 900),
        "img/p2.png": make_test_png(1600, 900),
        "img/p3.png": make_test_png(1600, 900),
        "img/p4.png": make_test_png(1600, 900),
        "img/p5.png": make_test_png(1600, 900),
        "img/top1.png": make_test_png(1600, 900),
        "img/top3.png": make_test_png(1600, 900),
    }
    return files


def _consumer_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "maatlog_responsive_images": True,
        "maatlog_home_docname": "index",
        "maatlog_page_size": 1,
        "maatlog_authors": {"alice": "Alice", "bob": "Bob"},
        "maatlog_author_profiles": {"alice": {"featured_posts": ["p1"]}},
        "templates_path": ["_templates"],
    }
    config.update(overrides)
    return config


def _consumer_generator() -> FakeVariantGenerator:
    probes = {name: PROBE for name in ("p1.png", "p2.png", "p3.png", "p4.png", "p5.png", "top1.png", "top3.png")}
    return CustomRecordingGenerator(probes)


def _load_snapshot(app: Sphinx, pagename: str) -> dict[str, Any]:
    path = Path(app.outdir) / "_responsive_test" / f"{pagename}.json"
    assert path.is_file(), f"missing snapshot for {pagename}"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _assert_reaches_file(app: Sphinx, pagename: str, url: str | None) -> None:
    assert url, f"empty url on {pagename}"
    target_uri = app.builder.get_target_uri(pagename)
    joined = urljoin("https://example.test/" + target_uri, url)
    relative = unquote(urlsplit(joined).path.lstrip("/"))
    assert (Path(app.outdir) / relative).is_file(), f"{url} from {pagename} reaches no file"


def _assert_entry_reaches(app: Sphinx, pagename: str, entry: Mapping[str, Any] | None, *, usage: str) -> None:
    assert isinstance(entry, dict), f"missing responsive entry on {pagename}"
    assert entry["usage"] == usage
    candidates = entry["candidates"]
    assert isinstance(candidates, list) and candidates
    candidate_list = cast(list[Any], candidates)
    assert entry["src"] == candidate_list[-1]["url"]
    expected_srcset = ", ".join(f"{item['url']} {item['width']}w" for item in candidate_list)
    assert entry["srcset"] == expected_srcset
    assert entry["width"] == 1600
    for item in candidate_list:
        _assert_reaches_file(app, pagename, item["url"])


def _build_consumers(make_sphinx: SphinxFactory, **overrides: object) -> Sphinx:
    app = make_sphinx(files=_consumer_files(), config=_consumer_config(**overrides))
    register_variant_generator_factory(app, _consumer_generator)
    app.connect("html-page-context", record_page_context, priority=900)
    app.build()
    return app


def test_responsive_views_cover_every_consumer(make_sphinx: SphinxFactory) -> None:
    app = _build_consumers(make_sphinx)

    # Home: featured 3 + latest 1 with retargeted usages.
    home = _load_snapshot(app, "index")
    assert [card["slug"] for card in home["featured"]] == ["p1", "p2", "p3"]  # type: ignore[union-attr]
    assert [card["slug"] for card in home["latest"]] == ["p4"]  # type: ignore[union-attr]
    assert [card["slug"] for card in home["posts"]] == ["p1", "p2", "p3", "p4"]  # type: ignore[union-attr]
    for card, usage in zip(home["featured"], ("home-lead", "home-secondary", "home-secondary"), strict=True):  # type: ignore[union-attr]
        _assert_entry_reaches(app, "index", card["responsive_image"], usage=usage)  # type: ignore[arg-type]
        _assert_reaches_file(app, "index", card["image_url"])  # type: ignore[arg-type]
    for card in home["latest"]:  # type: ignore[union-attr]
        _assert_entry_reaches(app, "index", card["responsive_image"], usage="home-latest")  # type: ignore[arg-type]

    # Archive root pagination and tag/author/month archives use archive-card.
    for pagename in ("blog", "blog/page/2", "blog/tag/sphinx", "blog/author/alice", "blog/month/2026-07"):
        snapshot = _load_snapshot(app, pagename)
        assert snapshot["posts"], f"no cards on {pagename}"  # type: ignore[union-attr]
        for card in snapshot["posts"]:  # type: ignore[union-attr]
            if card["responsive_image"] is None:
                assert card["image_url"] is None
                continue
            _assert_entry_reaches(app, pagename, card["responsive_image"], usage="archive-card")  # type: ignore[arg-type]
            _assert_reaches_file(app, pagename, card["image_url"])  # type: ignore[arg-type]

    # Post page: representative + top image with distinct usages.
    p1 = _load_snapshot(app, "p1")
    assert p1["post"] is not None
    _assert_entry_reaches(app, "p1", p1["post"]["responsive_image"], usage="post-representative")  # type: ignore[union-attr,index]
    _assert_entry_reaches(app, "p1", p1["post"]["responsive_top_image"], usage="post-top")  # type: ignore[union-attr,index]
    _assert_reaches_file(app, "p1", p1["post"]["image_url"])  # type: ignore[union-attr,index]
    _assert_reaches_file(app, "p1", p1["post"]["top_image_url"])  # type: ignore[union-attr,index]
    assert p1["post"]["image_url"] != p1["post"]["responsive_image"]["src"]  # type: ignore[union-attr,index]

    # MyST front matter post carries both projections as well.
    p3 = _load_snapshot(app, "p3")
    _assert_entry_reaches(app, "p3", p3["post"]["responsive_image"], usage="post-representative")  # type: ignore[union-attr,index]
    _assert_entry_reaches(app, "p3", p3["post"]["responsive_top_image"], usage="post-top")  # type: ignore[union-attr,index]

    # No-image post projects no responsive views but keeps the page.
    p6 = _load_snapshot(app, "p6")
    assert p6["post"] is not None
    assert p6["post"]["responsive_image"] is None  # type: ignore[union-attr,index]
    assert p6["post"]["responsive_top_image"] is None  # type: ignore[union-attr,index]
    assert p6["post"]["image_url"] is None  # type: ignore[union-attr,index]

    # Neighbours of the middle post reuse archive-card.
    neighbours = p3["navigation"]  # type: ignore[union-attr]
    assert neighbours["newer_post"]["slug"] == "p2"
    assert neighbours["older_post"]["slug"] == "p4"
    _assert_entry_reaches(app, "p3", neighbours["newer_post"]["responsive_image"], usage="archive-card")
    _assert_entry_reaches(app, "p3", neighbours["older_post"]["responsive_image"], usage="archive-card")

    # Profile featured cards reuse archive-card.
    profile_page = _load_snapshot(app, "blog/author/alice")
    assert profile_page["profile"] is not None
    featured = profile_page["profile"]["featured"]  # type: ignore[union-attr,index]
    assert [card["slug"] for card in featured] == ["p1"]
    _assert_entry_reaches(app, "blog/author/alice", featured[0]["responsive_image"], usage="archive-card")

    # Post-list component renders the responsive mapping through the test template.
    listing_html = (Path(app.outdir) / "listing.html").read_text(encoding="utf-8")
    assert 'data-test-responsive="archive-card"' in listing_html
    assert 'data-test-slug="p1"' in listing_html


def test_responsive_home_keeps_explicit_featured_order(make_sphinx: SphinxFactory) -> None:
    app = _build_consumers(make_sphinx, maatlog_featured_posts=["p5", "p4"])
    home = _load_snapshot(app, "index")
    assert [card["slug"] for card in home["featured"]] == ["p5", "p4", "p1"]  # type: ignore[union-attr]
    for card, usage in zip(home["featured"], ("home-lead", "home-secondary", "home-secondary"), strict=True):  # type: ignore[union-attr]
        _assert_entry_reaches(app, "index", card["responsive_image"], usage=usage)  # type: ignore[arg-type]

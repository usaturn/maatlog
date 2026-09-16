"""Real-image format and pixel integration tests (issue #217, task E).

Every build here uses the normal ``maatlog_responsive_images = True`` path with
the real Pillow backend registered by ``maatlog.extension`` -- no fake
generators, no injected views, no hand-placed candidate files. In-process
``make_sphinx`` builds cover the format matrix; ``RealProject`` covers the
``python -m sphinx`` CLI path in a fresh interpreter.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from conftest import HtmlPage, ProjectFactory, SphinxFactory
from fixtures.responsive_build_fixtures import record_page_context
from fixtures.responsive_image_html import img_attrs
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from fixtures.responsive_real_build import create_project
from fixtures.responsive_real_project import ImageCase, image_cases, project_config, project_files
from PIL import Image
from sphinx.application import Sphinx

import maatlog.responsive_images as responsive_backend
from maatlog._responsive_image_pixels import _srgb_profile_bytes
from maatlog.errors import MaatlogBuildError
from maatlog.image_contracts import BackendInfo, ImageFormat
from maatlog.responsive_image_build import responsive_manifest

_OUTPUT_DIR = "_images/maatlog"


def _expected_widths(case: ImageCase) -> list[int]:
    assert case.width is not None
    return sorted({480, 768, 960, 1200, 1600}.intersection(range(1, case.width)) | {case.width})


def _variant_path(app: Sphinx, basename: str) -> Path:
    return Path(app.outdir) / _OUTPUT_DIR / basename


def assert_real_entry(app: Sphinx, case: ImageCase, source_key: str) -> None:
    """Decode every published candidate of *source_key* with Pillow."""
    entry = responsive_manifest(app.env)[source_key]
    assert case.width is not None and case.height is not None
    assert [variant.width for variant in entry.variants] == _expected_widths(case)
    for variant in entry.variants:
        path = _variant_path(app, variant.public_basename)
        assert path.is_file()
        assert path.stat().st_size > 0
        with Image.open(path) as image:
            image.load()
            assert image.width == variant.width
            assert image.height == max(1, round(case.height * image.width / case.width))
            assert image.format == case.format
            assert not image.getexif()


def _build(make_sphinx: SphinxFactory, name: str, *, builder: str = "html", **config: object) -> Sphinx:
    merged = project_config()
    merged.update(config)
    app = make_sphinx(files=project_files(source_name=name, post_count=3), config=merged, builder=builder)
    app.build()
    return app


def _png_chunk_types(data: bytes) -> list[bytes]:
    """Parse PNG chunks by length prefix; never substring-scan the payload."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    found: list[bytes] = []
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        found.append(data[offset + 4 : offset + 8])
        offset += 12 + length
    return found


def _rgb_at(image: Image.Image, point: tuple[int, int]) -> tuple[int, ...]:
    """RGB channel values at *point*."""
    return tuple(int(channel) for channel in image.convert("RGB").getpixel(point)[:3])  # type: ignore[misc]


def _diagnostic_codes(error: pytest.ExceptionInfo[MaatlogBuildError]) -> list[str]:
    return [item.code for item in error.value.diagnostics]


def _page_path(builder: str, docname: str) -> str:
    return f"{docname}.html" if builder == "html" else f"{docname}/index.html"


def _outdir_file(root: Path, page_relpath: str, url: str) -> Path:
    """Resolve a page-relative URL to an output file (html builder layout)."""
    joined = urljoin(f"https://example.test/{page_relpath}", url)
    return root / unquote(urlsplit(joined).path.lstrip("/"))


# ---------------------------------------------------------------------------
# Step 1 -- the fixtures themselves


def test_image_cases_decode() -> None:
    cases = image_cases()
    assert cases["photo.jpg"].payload[:3] == b"\xff\xd8\xff"
    for name in ("rgba.png", "still.webp", "orientation-6.jpg"):
        case = cases[name]
        with Image.open(BytesIO(case.payload)) as image:
            image.load()
            assert image.width > 0 and image.height > 0
    for name in ("animated.gif", "animated.webp", "animated.png", "multipage.tiff"):
        with Image.open(BytesIO(cases[name].payload)) as image:
            assert getattr(image, "n_frames", 1) == 2
    with Image.open(BytesIO(cases["orientation-6.jpg"].payload)) as image:
        assert image.getexif()[274] == 6
    with Image.open(BytesIO(cases["icc.png"].payload)) as image:
        assert image.info.get("icc_profile") == _srgb_profile_bytes()
    with Image.open(BytesIO(cases["palette.png"].payload)) as image:
        image.load()
        assert image.mode == "P"
        assert "transparency" in image.info


def test_project_files_layout() -> None:
    files = project_files()
    expected_docs = {
        "index.rst",
        "listing.rst",
        "top-only.rst",
        "representative-only.rst",
        "no-image.rst",
        "general.rst",
        *(f"posts/p{index:02d}.md" for index in range(1, 16)),
    }
    assert expected_docs.issubset(files)
    assert files["images/photo.jpg"] == image_cases()["photo.jpg"].payload
    assert "maatlog-image: ../images/photo.jpg" in str(files["posts/p01.md"])
    assert "maatlog-top-image: ../images/photo.jpg" in str(files["posts/p01.md"])


# ---------------------------------------------------------------------------
# Step 3 -- real candidates, decoded


_RESPONSIVE_NAMES = [
    "photo.jpg",
    "rgba.png",
    "still.webp",
    "small.jpg",
    "portrait.jpg",
    "orientation-6.jpg",
]


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("name", _RESPONSIVE_NAMES)
def test_real_candidates_decode(make_sphinx: SphinxFactory, builder: str, name: str) -> None:
    case = image_cases()[name]
    app = _build(make_sphinx, name, builder=builder)
    assert_real_entry(app, case, f"images/{name}")


def test_small_image_only_240w(make_sphinx: SphinxFactory) -> None:
    app = _build(make_sphinx, "small.jpg")
    entry = responsive_manifest(app.env)["images/small.jpg"]
    assert [variant.width for variant in entry.variants] == [240]


def test_unsorted_duplicate_widths_normalize(make_sphinx: SphinxFactory) -> None:
    app = _build(make_sphinx, "photo.jpg", maatlog_responsive_image_widths=(768, 480, 480))
    entry = responsive_manifest(app.env)["images/photo.jpg"]
    assert [variant.width for variant in entry.variants] == [480, 768, 2400]


def test_content_sniff_overrides_extension(make_sphinx: SphinxFactory) -> None:
    """JPEG bytes behind a ``.png`` name produce JPEG candidates named ``.jpg``."""
    case = image_cases()["mislabeled.png"]
    app = _build(make_sphinx, "mislabeled.png")
    entry = responsive_manifest(app.env)["images/mislabeled.png"]
    assert entry.image_format is ImageFormat.JPEG
    assert_real_entry(app, case, "images/mislabeled.png")
    for variant in entry.variants:
        assert variant.public_basename.endswith(".jpg")


def test_rgba_alpha_matches_independent_lanczos(make_sphinx: SphinxFactory) -> None:
    """The half-size RGBA candidate matches a fresh LANCZOS oracle within ±1."""
    case = image_cases()["rgba.png"]
    app = _build(make_sphinx, "rgba.png")
    entry = responsive_manifest(app.env)["images/rgba.png"]
    variant = next(item for item in entry.variants if item.width == 480)
    path = _variant_path(app, variant.public_basename)
    with Image.open(path) as actual:
        actual.load()
        assert actual.mode == "RGBA"
        actual_pixels = actual.copy()
    with Image.open(BytesIO(case.payload)) as source:
        source.load()
        oracle = source.convert("RGBA").resize(  # pyright: ignore[reportUnknownMemberType]
            actual_pixels.size, Image.Resampling.LANCZOS
        )
    assert oracle.size == (480, 270)
    points = [(x, y) for x in (40, 240, 440) for y in (30, 135, 240)]
    for point in points:
        actual_pixel = actual_pixels.getpixel(point)
        oracle_pixel = oracle.getpixel(point)
        assert all(abs(int(a) - int(o)) <= 1 for a, o in zip(actual_pixel, oracle_pixel, strict=True))  # type: ignore[misc]


def test_icc_png_keeps_srgb_profile(make_sphinx: SphinxFactory) -> None:
    app = _build(make_sphinx, "icc.png")
    entry = responsive_manifest(app.env)["images/icc.png"]
    for variant in entry.variants:
        with Image.open(_variant_path(app, variant.public_basename)) as image:
            image.load()
            assert image.info.get("icc_profile") == _srgb_profile_bytes()


def test_cmyk_jpeg_keeps_mode(make_sphinx: SphinxFactory) -> None:
    app = _build(make_sphinx, "cmyk.jpg")
    entry = responsive_manifest(app.env)["images/cmyk.jpg"]
    assert_real_entry(app, image_cases()["cmyk.jpg"], "images/cmyk.jpg")
    for variant in entry.variants:
        with Image.open(_variant_path(app, variant.public_basename)) as image:
            image.load()
            assert image.mode == "CMYK"


def test_palette_trns_becomes_rgba(make_sphinx: SphinxFactory) -> None:
    app = _build(make_sphinx, "palette.png")
    entry = responsive_manifest(app.env)["images/palette.png"]
    assert_real_entry(app, image_cases()["palette.png"], "images/palette.png")
    variant = next(item for item in entry.variants if item.width == 480)
    with Image.open(_variant_path(app, variant.public_basename)) as image:
        image.load()
        assert image.mode == "RGBA"
        # Palette index 0 (tRNS transparent) covers the left half.
        assert image.getpixel((5, image.height // 2))[3] <= 1  # type: ignore[index]
        assert image.getpixel((image.width - 5, image.height // 2))[3] >= 254  # type: ignore[index]


def test_orientation_bakes_block_positions(make_sphinx: SphinxFactory) -> None:
    """EXIF orientation 6 turns the stored left/right halves into top/bottom."""
    app = _build(make_sphinx, "orientation-6.jpg")
    entry = responsive_manifest(app.env)["images/orientation-6.jpg"]
    assert entry.natural_width == 800
    assert entry.natural_height == 1200
    variant = next(item for item in entry.variants if item.width == 800)
    with Image.open(_variant_path(app, variant.public_basename)) as image:
        rgb = image.convert("RGB")
        top = rgb.getpixel((rgb.width // 2, rgb.height // 4))
        bottom = rgb.getpixel((rgb.width // 2, rgb.height * 3 // 4))
    assert top[0] > 150 and top[2] < 100, f"top block should be red, got {top}"  # type: ignore[index]
    assert bottom[2] > 150 and bottom[0] < 100, f"bottom block should be blue, got {bottom}"  # type: ignore[index]


def test_lossy_block_centers_within_tolerance(make_sphinx: SphinxFactory) -> None:
    """Lossy candidates stay within 16 per channel of the flat block colours."""
    app = _build(make_sphinx, "still.webp")
    entry = responsive_manifest(app.env)["images/still.webp"]
    variant = next(item for item in entry.variants if item.width == 480)
    with Image.open(_variant_path(app, variant.public_basename)) as image:
        left = _rgb_at(image, (image.width // 4, image.height // 2))
        right = _rgb_at(image, (image.width * 3 // 4, image.height // 2))
    assert all(abs(channel - expected) <= 16 for channel, expected in zip(left, (200, 30, 30), strict=True))
    assert all(abs(channel - expected) <= 16 for channel, expected in zip(right, (30, 30, 200), strict=True))


@pytest.mark.parametrize("name", ["meta.jpg", "meta.png"])
def test_variants_strip_all_metadata(make_sphinx: SphinxFactory, name: str) -> None:
    app = _build(make_sphinx, name)
    entry = responsive_manifest(app.env)[f"images/{name}"]
    for variant in entry.variants:
        path = _variant_path(app, variant.public_basename)
        raw = path.read_bytes()
        with Image.open(path) as image:
            image.load()
            assert not image.getexif()
            for key in ("exif", "xmp", "comment"):
                assert image.info.get(key) is None
            assert getattr(image, "text", None) in (None, {})
        if name.endswith(".png"):
            forbidden = {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}
            assert not forbidden.intersection(_png_chunk_types(raw))
            assert b"secret-" not in raw
        else:
            # A stripped JPEG carries no APP1 (EXIF/XMP) or COM segments.
            assert b"Exif\x00\x00" not in raw
            assert b"secret-comment" not in raw
            assert b"<x:xmp>" not in raw
            assert b"\xff\xe1" not in raw
            assert b"\xff\xfe" not in raw


@pytest.mark.parametrize("name", ["my photo.png", "a,b.png", "日本語.png", "100%.png"])
def test_special_names_get_safe_published_basenames(make_sphinx: SphinxFactory, name: str) -> None:
    app = _build(make_sphinx, name)
    entry = responsive_manifest(app.env)[f"images/{name}"]
    assert entry.variants
    for variant in entry.variants:
        assert re.fullmatch(r"[A-Za-z0-9._-]+", variant.public_basename)
        assert _variant_path(app, variant.public_basename).is_file()


def test_same_basename_different_directories_stay_distinct(make_sphinx: SphinxFactory) -> None:
    case = image_cases()["dup.png"]
    files = project_files(source_name="dup.png", post_count=3)
    files["alt/dup.png"] = case.payload  # identical bytes, different path
    files["posts/extra.md"] = (
        "---\nmaatlog-post: true\nmaatlog-slug: extra\n"
        "maatlog-published-at: 2026-07-19T09:00:00Z\n"
        "maatlog-image: ../alt/dup.png\n---\n# EXTRA\n\nBody.\n"
    )
    # index.rst is already written; append the new doc to its hidden toctree.
    index = str(files["index.rst"])
    assert "   posts/p03\n" in index
    files["index.rst"] = index.replace("   posts/p03\n", "   posts/p03\n   posts/extra\n")
    app = make_sphinx(files=files, config=project_config())
    app.build()
    manifest = responsive_manifest(app.env)
    first = manifest["images/dup.png"]
    second = manifest["alt/dup.png"]
    names = [variant.public_basename for variant in first.variants]
    names += [variant.public_basename for variant in second.variants]
    assert all(name.startswith("dup-") for name in names)
    assert len(set(names)) == len(names)
    for name in names:
        assert _variant_path(app, name).is_file()


def test_source_bytes_stay_untouched_and_original_published(make_sphinx: SphinxFactory) -> None:
    case = image_cases()["photo.jpg"]
    app = _build(make_sphinx, "photo.jpg")
    assert (Path(app.srcdir) / "images" / "photo.jpg").read_bytes() == case.payload
    published = Path(app.outdir) / "_images" / app.builder.images["images/photo.jpg"]
    assert published.read_bytes() == case.payload


# ---------------------------------------------------------------------------
# Step 4 -- fallbacks, failures, validation


_FALLBACK_NAMES = [
    "vector.svg",
    "still.gif",
    "animated.gif",
    "animated.png",
    "animated.webp",
    "multipage.tiff",
]


@pytest.mark.parametrize("name", _FALLBACK_NAMES)
def test_fallback_source_publishes_original_verbatim(make_sphinx: SphinxFactory, name: str) -> None:
    case = image_cases()[name]
    app = _build(make_sphinx, name)
    manifest = responsive_manifest(app.env)
    assert f"images/{name}" not in manifest
    published = Path(app.outdir) / "_images" / app.builder.images[f"images/{name}"]
    assert published.read_bytes() == case.payload
    html = (Path(app.outdir) / "posts" / "p01.html").read_text(encoding="utf-8")
    managed = [attrs for attrs in img_attrs(html) if "maatlog" in attrs.get("class", "")]
    assert managed, "expected representative/top images on p01"
    for attrs in managed:
        assert "srcset" not in attrs
        assert "sizes" not in attrs


_CORRUPT_NAMES = ["truncated.jpg", "truncated.png", "truncated.webp", "broken-anim.webp"]


@pytest.mark.parametrize("name", _CORRUPT_NAMES)
def test_corrupt_source_fails_without_partial_state(make_sphinx: SphinxFactory, name: str) -> None:
    app = make_sphinx(files=project_files(source_name=name, post_count=3), config=project_config())
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert "maatlog.image.decode-failed" in _diagnostic_codes(error)
    assert responsive_manifest(app.env) == {}
    assert not (Path(app.outdir) / _OUTPUT_DIR).exists()


def test_missing_codec_reports_codec_missing(make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Boundary mock: only ``describe_backend`` shrinks; the rest stays real."""
    generator_type = responsive_backend.PillowImageVariantGenerator
    original = generator_type.describe_backend

    def narrower(self: responsive_backend.PillowImageVariantGenerator) -> BackendInfo:
        info = original(self)
        return replace(info, supported_formats=frozenset({ImageFormat.JPEG, ImageFormat.PNG}))

    monkeypatch.setattr(generator_type, "describe_backend", narrower)
    app = make_sphinx(files=project_files(source_name="still.webp", post_count=3), config=project_config())
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert "maatlog.image.codec-missing" in _diagnostic_codes(error)
    assert responsive_manifest(app.env) == {}
    assert not (Path(app.outdir) / _OUTPUT_DIR).exists()


def test_encode_failure_reports_diagnostic(make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail injection limited to the encoder function the real generator calls."""

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected encode failure")

    monkeypatch.setattr(responsive_backend, "_encode_variant", boom)
    app = make_sphinx(files=project_files(source_name="photo.jpg", post_count=3), config=project_config())
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert "maatlog.image.encode-failed" in _diagnostic_codes(error)
    assert responsive_manifest(app.env) == {}
    assert not (Path(app.outdir) / _OUTPUT_DIR).exists()


def test_too_large_source_reports_diagnostic(make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000_000)
    app = make_sphinx(files=project_files(source_name="photo.jpg", post_count=3), config=project_config())
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    assert "maatlog.image.too-large" in _diagnostic_codes(error)
    assert responsive_manifest(app.env) == {}
    assert not (Path(app.outdir) / _OUTPUT_DIR).exists()


def test_symlinked_source_is_rejected(make_project: ProjectFactory, tmp_path: Path) -> None:
    project = make_project(files=project_files(source_name="photo.jpg", post_count=3), config=project_config())
    target = tmp_path / "outside.png"
    target.write_bytes(image_cases()["rgba.png"].payload)
    link = project.srcdir / "images" / "photo.jpg"
    link.unlink()
    link.symlink_to(target)
    with pytest.raises(MaatlogBuildError) as error:
        project.build()
    assert "maatlog.image.invalid" in _diagnostic_codes(error)


@pytest.mark.parametrize("suffix", ["?v=2", "#frag"])
def test_query_and_fragment_sources_are_rejected(make_project: ProjectFactory, suffix: str) -> None:
    files = project_files(source_name="photo.jpg", post_count=3)
    post = str(files["posts/p01.md"])
    files["posts/p01.md"] = post.replace("../images/photo.jpg", f"../images/photo.jpg{suffix}")
    project = make_project(files=files, config=project_config())
    with pytest.raises(MaatlogBuildError) as error:
        project.build()
    assert "maatlog.image.invalid" in _diagnostic_codes(error)


# ---------------------------------------------------------------------------
# Step 4 -- every consumer renders the real pipeline output


def _snapshot(app: Sphinx, pagename: str) -> dict[str, Any]:
    path = Path(app.outdir) / "_responsive_test" / f"{pagename}.json"
    assert path.is_file(), f"missing snapshot for {pagename}"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _reaches(app: Sphinx, pagename: str, url: str | None) -> None:
    assert url, f"empty url on {pagename}"
    target = _outdir_file(Path(app.outdir), app.builder.get_target_uri(pagename), url)
    assert target.is_file(), f"{url} from {pagename} reaches no file"


def _check_entry(app: Sphinx, pagename: str, entry: Any, usage: str) -> None:
    assert isinstance(entry, dict), f"missing responsive entry on {pagename}"
    assert entry["usage"] == usage
    candidates = cast(list[Any], entry["candidates"])
    assert candidates
    for item in candidates:
        assert isinstance(item, dict)
        _reaches(app, pagename, cast(str, item["url"]))


def test_consumers_project_real_entries(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=project_files(), config=project_config())
    app.connect("html-page-context", record_page_context, priority=900)
    app.build()

    home = _snapshot(app, "index")
    assert [card["slug"] for card in home["featured"]] == ["p01", "p02", "p03"]
    for card, usage in zip(home["featured"], ("home-lead", "home-secondary", "home-secondary"), strict=True):
        _check_entry(app, "index", card["responsive_image"], usage)
    imaged_latest = [card for card in home["latest"] if card["responsive_image"] is not None]
    assert imaged_latest, "no imaged latest card on index"
    for card in imaged_latest:
        _check_entry(app, "index", card["responsive_image"], "home-latest")

    archive_pages = (
        "nested/blog",
        "nested/blog/tag/integration",
        "nested/blog/category/photos",
        "nested/blog/author/alice",
        "nested/blog/month/2026-07",
    )
    for pagename in archive_pages:
        snapshot = _snapshot(app, pagename)
        assert snapshot["posts"], f"no cards on {pagename}"
        imaged = [card for card in snapshot["posts"] if card["responsive_image"] is not None]
        assert imaged, f"no imaged card on {pagename}"
        for card in imaged:
            _check_entry(app, pagename, card["responsive_image"], "archive-card")

    p01 = _snapshot(app, "posts/p01")
    assert p01["post"] is not None
    _check_entry(app, "posts/p01", p01["post"]["responsive_image"], "post-representative")
    _check_entry(app, "posts/p01", p01["post"]["responsive_top_image"], "post-top")

    top_only = _snapshot(app, "top-only")
    assert top_only["post"]["responsive_image"] is None
    _check_entry(app, "top-only", top_only["post"]["responsive_top_image"], "post-top")

    rep_only = _snapshot(app, "representative-only")
    _check_entry(app, "representative-only", rep_only["post"]["responsive_image"], "post-representative")
    assert rep_only["post"]["responsive_top_image"] is None

    no_image = _snapshot(app, "no-image")
    assert no_image["post"]["responsive_image"] is None
    assert no_image["post"]["responsive_top_image"] is None

    profile = _snapshot(app, "nested/blog/author/alice")
    assert profile["profile"] is not None
    featured = profile["profile"]["featured"]
    assert featured and featured[0]["slug"] == "p01"
    _check_entry(app, "nested/blog/author/alice", featured[0]["responsive_image"], "archive-card")


def _assert_responsive_img(attrs: dict[str, str] | None, label: str) -> dict[str, str]:
    assert attrs is not None, f"missing img for {label}"
    assert attrs.get("data-maatlog-srcset") == "w-v1", label
    assert "srcset" in attrs and "sizes" in attrs, label
    assert "width" in attrs and "height" in attrs, label
    return attrs


def test_consumer_html_marks_every_site(tmp_path: Path) -> None:
    """A real CLI build: every consumer template emits the managed marker."""
    project = create_project(tmp_path / "consumers", source_name="photo.jpg")
    result = project.build()
    assert result.returncode == 0, result.stderr + result.stdout

    def page(docname: str) -> HtmlPage:
        return HtmlPage((project.outdir / _page_path("html", docname)).read_text(encoding="utf-8"))

    post = page("posts/p01")
    hero = _assert_responsive_img(post.select_one("img.maatlog-post-hero-image"), "post hero")
    top = _assert_responsive_img(post.select_one("img.maatlog-post-top-image-img"), "post top")
    for attrs in (hero, top):
        for candidate in attrs["srcset"].split(", "):
            url = candidate.rsplit(" ", 1)[0]
            assert _outdir_file(project.outdir, "posts/p01.html", url).is_file()

    home = page("index")
    _assert_responsive_img(home.select_one(".maatlog-post-card-lead .maatlog-post-card-image"), "home lead")
    secondary = home.select(".maatlog-post-card-secondary .maatlog-post-card-image")
    assert len(secondary) == 2
    for attrs in secondary:
        _assert_responsive_img(attrs, "home secondary")
    latest = home.select(".maatlog-post-card[data-maatlog-card-variant='latest'] .maatlog-post-card-image")
    assert latest
    for attrs in latest:
        _assert_responsive_img(attrs, "home latest")

    for docname in (
        "nested/blog",
        "nested/blog/tag/integration",
        "nested/blog/category/photos",
        "nested/blog/author/alice",
        "nested/blog/month/2026-07",
    ):
        cards = page(docname).select(".maatlog-post-card .maatlog-post-card-image")
        assert cards, f"no post cards on {docname}"
        for attrs in cards:
            _assert_responsive_img(attrs, docname)

    # The normal post-list directive independently renders the marker.
    listing = page("listing")
    listed = listing.select("[data-maatlog-component='post-list'] .maatlog-post-card-image")
    assert listed
    for attrs in listed:
        _assert_responsive_img(attrs, "listing post-list")

    # Plain body images -- local and remote -- stay single-source.
    general = page("general")
    remote = general.select_one("img[src='https://example.test/remote.png']")
    assert remote is not None
    assert "srcset" not in remote
    local = [attrs for attrs in img_attrs(general.text) if attrs.get("src", "").endswith("body.png")]
    assert local and all("srcset" not in attrs for attrs in local)


def test_scroll_pages_share_the_same_source(tmp_path: Path) -> None:
    project = create_project(tmp_path / "scroll", source_name="photo.jpg", page_size=4)
    result = project.build()
    assert result.returncode == 0, result.stderr + result.stdout
    for docname in ("nested/blog", "nested/blog/page/2", "nested/blog/page/5"):
        page = HtmlPage((project.outdir / _page_path("html", docname)).read_text(encoding="utf-8"))
        cards = page.select(".maatlog-post-card .maatlog-post-card-image")
        assert cards, f"no cards on {docname}"
        for attrs in cards:
            _assert_responsive_img(attrs, docname)


# ---------------------------------------------------------------------------
# Step 2 -- the subprocess driver itself


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_subprocess_build_produces_real_candidates(tmp_path: Path, builder: str) -> None:
    project = create_project(tmp_path / f"cli-{builder}", builder=builder, source_name="photo.jpg", post_count=3)
    result = project.build()
    assert result.returncode == 0, result.stderr + result.stdout
    output = project.outdir / _OUTPUT_DIR
    published = sorted(output.glob("*.jpg"))
    assert len(published) == 6
    widths: list[int] = []
    for path in published:
        with Image.open(path) as image:
            image.load()
            widths.append(image.width)
            assert image.format == "JPEG"
            assert not image.getexif()
    assert sorted(widths) == [480, 768, 960, 1200, 1600, 2400]
    cache = project.doctreedir / "maatlog_responsive_images"
    assert any(cache.rglob("*.jpg"))
    page = HtmlPage((project.outdir / _page_path(builder, "posts/p01")).read_text(encoding="utf-8"))
    hero = _assert_responsive_img(page.select_one("img.maatlog-post-hero-image"), "post hero")
    assert "2400w" in hero["srcset"]


def test_subprocess_parallel_and_fresh_builds(tmp_path: Path) -> None:
    project = create_project(tmp_path / "cli-parallel", source_name="photo.jpg", post_count=3)
    first = project.build(parallel=2)
    assert first.returncode == 0, first.stderr + first.stdout
    second = project.build(fresh=True)
    assert second.returncode == 0, second.stderr + second.stdout
    assert len(list((project.outdir / _OUTPUT_DIR).glob("*.jpg"))) == 6


def test_subprocess_decode_failure_diagnostic(tmp_path: Path) -> None:
    project = create_project(tmp_path / "cli-corrupt", source_name="truncated.jpg", post_count=3)
    result = project.build()
    assert result.returncode != 0
    assert "maatlog.image.decode-failed" in result.stderr + result.stdout
    assert not (project.outdir / _OUTPUT_DIR).exists()


def test_subprocess_invalid_widths_fail(tmp_path: Path) -> None:
    project = create_project(
        tmp_path / "cli-widths",
        source_name="photo.jpg",
        post_count=3,
        config={"maatlog_responsive_image_widths": (0,)},
    )
    result = project.build()
    assert result.returncode != 0
    assert "maatlog.config.invalid" in result.stderr + result.stdout


def test_subprocess_disabled_build_never_imports_backend(tmp_path: Path) -> None:
    """An OFF build of the same real project must not load the Pillow backend."""
    project = create_project(tmp_path / "cli-off", enabled=False, source_name="photo.jpg", post_count=3)
    guard = (
        "\nimport sys\n\n\n"
        "def setup(app):\n"
        "    def check(_app, exception):\n"
        "        leaked = sorted(\n"
        "            name for name in sys.modules\n"
        "            if name == 'maatlog.responsive_images'"
        " or name.startswith('maatlog._responsive_image')\n"
        "        )\n"
        "        assert not leaked, leaked\n"
        "    app.connect('build-finished', check)\n"
    )
    conf = project.srcdir / "conf.py"
    conf.write_text(conf.read_text(encoding="utf-8") + guard, encoding="utf-8")
    result = project.build()
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (project.outdir / _OUTPUT_DIR).exists()
    page = (project.outdir / "posts" / "p01.html").read_text(encoding="utf-8")
    assert "data-maatlog-srcset" not in page

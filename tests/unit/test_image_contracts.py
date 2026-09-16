from __future__ import annotations

import pickle
from dataclasses import fields, replace
from pathlib import Path, PurePosixPath

import pytest

from maatlog.config import MaatlogConfig
from maatlog.errors import Diagnostic, format_diagnostic
from maatlog.image_contracts import (
    CACHE_SCHEMA_VERSION,
    DEFAULT_ENCODER_PROFILE,
    FORMAT_EXTENSIONS,
    IMAGE_BACKEND_MISSING,
    IMAGE_CACHE_UNWRITABLE,
    IMAGE_CODEC_MISSING,
    IMAGE_DECODE_FAILED,
    IMAGE_ENCODE_FAILED,
    IMAGE_TOO_LARGE,
    RESPONSIVE_CACHE_DIRNAME,
    RESPONSIVE_OUTPUT_SUBDIR,
    SNIFF_HEADER_BYTES,
    BackendInfo,
    EncoderProfile,
    GeneratedVariant,
    ImageFetchPriority,
    ImageFormat,
    ImageLoading,
    ImageProcessingError,
    ImageUsage,
    ImageVariantGenerator,
    ResponsiveImageCandidate,
    ResponsiveImageEntry,
    ResponsiveVariant,
    SourceImageIdentity,
    SourceImageProbe,
    VariantRequest,
    build_responsive_image_view,
    build_source_identity,
    compute_content_hash,
    compute_variant_key,
    responsive_images_enabled,
    scaled_height,
    select_candidate_widths,
    sniff_image_format,
    sniff_source_format,
    variant_cache_relpath,
    variant_public_basename,
)

JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
WEBP_HEADER = b"RIFF\x24\x00\x00\x00WEBPVP8 "
GIF87A = b"GIF87a\x01\x00\x01\x00"
GIF89A = b"GIF89a\x01\x00\x01\x00"
SVG_PLAIN = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
SVG_XML_DECL = b'<?xml version="1.0"?><svg></svg>'
SVG_BOM = b"\xef\xbb\xbf<svg></svg>"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (JPEG_HEADER, ImageFormat.JPEG),
        (PNG_HEADER, ImageFormat.PNG),
        (WEBP_HEADER, ImageFormat.WEBP),
        (GIF87A, None),
        (GIF89A, None),
        (SVG_PLAIN, None),
        (SVG_XML_DECL, None),
        (SVG_BOM, None),
        (b"", None),
        (b"\xff\xd8", None),
        (b"RIFF\x24\x00\x00\x00WAVE", None),
        (b"not an image at all", None),
    ],
)
def test_sniff_image_format(header: bytes, expected: ImageFormat | None) -> None:
    assert sniff_image_format(header) is expected


def test_sniff_source_format_ignores_extension(tmp_path: Path) -> None:
    misnamed = tmp_path / "photo.png"
    misnamed.write_bytes(JPEG_HEADER + b"\x00" * 64)
    assert sniff_source_format(misnamed) is ImageFormat.JPEG


def test_sniff_source_format_reads_only_the_header(tmp_path: Path) -> None:
    target = tmp_path / "big.png"
    target.write_bytes(PNG_HEADER + b"\x00" * 4096)
    assert sniff_source_format(target) is ImageFormat.PNG
    assert SNIFF_HEADER_BYTES < 4096


def test_sniff_source_format_returns_none_for_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "empty.png"
    target.write_bytes(b"")
    assert sniff_source_format(target) is None


def test_sniff_source_format_propagates_oserror(tmp_path: Path) -> None:
    """An unreadable path is a failure, not an unsupported format."""
    with pytest.raises(OSError):
        sniff_source_format(tmp_path / "missing.png")


def test_format_extensions_cover_every_format() -> None:
    assert set(FORMAT_EXTENSIONS) == set(ImageFormat)
    assert FORMAT_EXTENSIONS[ImageFormat.JPEG] == ".jpg"
    assert FORMAT_EXTENSIONS[ImageFormat.PNG] == ".png"
    assert FORMAT_EXTENSIONS[ImageFormat.WEBP] == ".webp"


def test_usage_values_are_stable() -> None:
    assert [item.value for item in ImageUsage] == [
        "post-top",
        "post-representative",
        "home-lead",
        "home-secondary",
        "home-latest",
        "archive-card",
    ]


def test_loading_and_priority_values_are_stable() -> None:
    assert [item.value for item in ImageLoading] == ["eager", "lazy"]
    assert [item.value for item in ImageFetchPriority] == ["high", "auto", "low"]


IDENTITY = SourceImageIdentity(source_relpath="posts/img/hero.jpg", content_hash="a" * 64)
BACKEND = BackendInfo(
    backend_id="pillow",
    backend_version="11.3.0",
    codec_versions=(("jpeg", "9.6.0"), ("zlib", "1.3.1")),
    supported_formats=frozenset({ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP}),
    pipeline_schema=1,
)


def key(**overrides: object) -> str:
    arguments: dict[str, object] = {
        "identity": IDENTITY,
        "width": 768,
        "image_format": ImageFormat.JPEG,
        "encoder": DEFAULT_ENCODER_PROFILE,
        "backend": BACKEND,
    }
    arguments.update(overrides)
    return compute_variant_key(**arguments)  # type: ignore[arg-type]


def test_content_hash_is_sha256_of_file_bytes(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"maatlog")
    import hashlib

    assert compute_content_hash(target) == hashlib.sha256(b"maatlog").hexdigest()


def test_build_source_identity_uses_posix_relative_path(tmp_path: Path) -> None:
    srcdir = tmp_path / "src"
    image = srcdir / "posts" / "img" / "hero.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"bytes")
    identity = build_source_identity(image, srcdir=srcdir)
    assert identity.source_relpath == "posts/img/hero.jpg"
    assert identity.content_hash == compute_content_hash(image)


def test_variant_key_is_stable_for_the_same_inputs() -> None:
    assert key() == key()
    assert len(key()) == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"identity": SourceImageIdentity(source_relpath="other/hero.jpg", content_hash="a" * 64)},
        {"identity": SourceImageIdentity(source_relpath="posts/img/hero.jpg", content_hash="b" * 64)},
        {"width": 960},
        {"image_format": ImageFormat.WEBP},
        {"encoder": EncoderProfile(profile_id="other")},
        {
            "backend": BackendInfo(
                backend_id="other",
                backend_version="11.3.0",
                codec_versions=(("jpeg", "9.6.0"), ("zlib", "1.3.1")),
                supported_formats=frozenset({ImageFormat.JPEG}),
                pipeline_schema=1,
            )
        },
        {
            "backend": BackendInfo(
                backend_id="pillow",
                backend_version="12.0.0",
                codec_versions=(("jpeg", "9.6.0"), ("zlib", "1.3.1")),
                supported_formats=frozenset({ImageFormat.JPEG}),
                pipeline_schema=1,
            )
        },
        {
            "backend": BackendInfo(
                backend_id="pillow",
                backend_version="11.3.0",
                codec_versions=(("jpeg", "9.7.0"), ("zlib", "1.3.1")),
                supported_formats=frozenset({ImageFormat.JPEG}),
                pipeline_schema=1,
            )
        },
        {
            "backend": BackendInfo(
                backend_id="pillow",
                backend_version="11.3.0",
                codec_versions=(("jpeg", "9.6.0"), ("zlib", "1.3.1")),
                supported_formats=frozenset({ImageFormat.JPEG}),
                pipeline_schema=2,
            )
        },
    ],
)
def test_variant_key_changes_with_every_input(overrides: dict[str, object]) -> None:
    assert key(**overrides) != key()


def test_variant_key_changes_with_encoder_values() -> None:
    """Every encoder field feeds the key, even when ``profile_id`` is unchanged."""
    changed = replace(DEFAULT_ENCODER_PROFILE, jpeg_quality=95)
    assert changed.profile_id == DEFAULT_ENCODER_PROFILE.profile_id
    assert key(encoder=changed) != key()


def test_variant_key_changes_for_every_encoder_field() -> None:
    """No encoder field may be positionally excluded from the key."""
    for field in fields(EncoderProfile):
        current = getattr(DEFAULT_ENCODER_PROFILE, field.name)
        if isinstance(current, bool):
            changed = replace(DEFAULT_ENCODER_PROFILE, **{field.name: not current})
        elif isinstance(current, int):
            changed = replace(DEFAULT_ENCODER_PROFILE, **{field.name: current + 1})
        else:
            changed = replace(DEFAULT_ENCODER_PROFILE, **{field.name: f"{current}-changed"})
        assert key(encoder=changed) != key(), field.name


def test_variant_key_ignores_supported_formats() -> None:
    """``supported_formats`` describes the backend's capability, not the output bytes."""
    narrowed = BackendInfo(
        backend_id="pillow",
        backend_version="11.3.0",
        codec_versions=(("jpeg", "9.6.0"), ("zlib", "1.3.1")),
        supported_formats=frozenset({ImageFormat.JPEG}),
        pipeline_schema=1,
    )
    assert key(backend=narrowed) == key()


def test_backend_codec_fingerprint_is_sorted() -> None:
    backend = BackendInfo(
        backend_id="pillow",
        backend_version="11.3.0",
        codec_versions=(("zlib", "1.3.1"), ("jpeg", "9.6.0")),
        supported_formats=frozenset({ImageFormat.JPEG}),
        pipeline_schema=1,
    )
    assert backend.codec_fingerprint == "jpeg=9.6.0,zlib=1.3.1"


def test_default_encoder_profile_values_are_pinned() -> None:
    profile = DEFAULT_ENCODER_PROFILE
    assert profile.profile_id == "maatlog-encoder-1"
    assert profile.resample == "lanczos"
    assert profile.jpeg_quality == 82
    assert profile.jpeg_progressive is True
    assert profile.jpeg_optimize is True
    assert profile.jpeg_subsampling == 2
    assert profile.png_optimize is True
    assert profile.png_compress_level == 9
    assert profile.webp_quality == 82
    assert profile.webp_method == 6
    assert profile.webp_alpha_quality == 100
    assert profile.webp_exact is True


def test_policy_identifiers_are_pinned() -> None:
    from maatlog.image_contracts import ICC_POLICY_ID, METADATA_POLICY_ID, ORIENTATION_POLICY_ID

    assert CACHE_SCHEMA_VERSION == 1
    assert ORIENTATION_POLICY_ID == "exif-transpose-1"
    assert METADATA_POLICY_ID == "strip-exif-gps-xmp-1"
    assert ICC_POLICY_ID == "preserve-or-srgb-1"


def test_variant_cache_relpath_shards_by_key_prefix() -> None:
    value = key()
    assert variant_cache_relpath(value, ImageFormat.JPEG) == PurePosixPath(f"{value[:2]}/{value}.jpg")


@pytest.mark.parametrize(
    ("relpath", "expected_stem"),
    [
        ("posts/img/hero.jpg", "hero"),
        ("posts/img/写真.jpg", "image"),
        ("posts/img/my photo (1).jpg", "my-photo-1"),
        ("posts/img/...jpg", "image"),
        ("posts/img/" + "x" * 80 + ".jpg", "x" * 40),
    ],
)
def test_variant_public_basename_is_ascii_and_safe(relpath: str, expected_stem: str) -> None:
    identity = SourceImageIdentity(source_relpath=relpath, content_hash="a" * 64)
    value = compute_variant_key(
        identity=identity,
        width=768,
        image_format=ImageFormat.JPEG,
        encoder=DEFAULT_ENCODER_PROFILE,
        backend=BACKEND,
    )
    basename = variant_public_basename(identity=identity, key=value, width=768, image_format=ImageFormat.JPEG)
    assert basename == f"{expected_stem}-768w-{value[:16]}.jpg"
    assert basename.isascii()
    assert "/" not in basename


def test_variant_public_basename_differs_per_key() -> None:
    first = variant_public_basename(identity=IDENTITY, key=key(), width=768, image_format=ImageFormat.JPEG)
    second = variant_public_basename(identity=IDENTITY, key=key(width=960), width=960, image_format=ImageFormat.JPEG)
    assert first != second


def test_identity_is_picklable() -> None:
    assert pickle.loads(pickle.dumps(IDENTITY)) == IDENTITY


WIDTHS = (480, 768, 960, 1200, 1600)


@pytest.mark.parametrize(
    ("natural_width", "expected"),
    [
        (2400, (480, 768, 960, 1200, 1600, 2400)),
        (1600, (480, 768, 960, 1200, 1600)),
        (1000, (480, 768, 960, 1000)),
        (480, (480,)),
        (300, (300,)),
        (1, (1,)),
    ],
)
def test_select_candidate_widths(natural_width: int, expected: tuple[int, ...]) -> None:
    assert select_candidate_widths(WIDTHS, natural_width) == expected


def test_select_candidate_widths_normalizes_unsorted_and_duplicated_input() -> None:
    assert select_candidate_widths([1200, 480, 480, 768], 2000) == (480, 768, 1200, 2000)


def test_select_candidate_widths_never_upscales() -> None:
    for natural_width in (1, 7, 479, 480, 481, 5000):
        assert max(select_candidate_widths(WIDTHS, natural_width)) == natural_width


@pytest.mark.parametrize(
    ("natural", "target", "expected"),
    [
        ((1600, 900), 480, 270),
        ((1600, 900), 1600, 900),
        ((100, 3), 10, 1),
        ((100, 75), 50, 38),
        ((100, 75), 100, 75),
        ((3, 100), 1, 33),
    ],
)
def test_scaled_height(natural: tuple[int, int], target: int, expected: int) -> None:
    natural_width, natural_height = natural
    assert scaled_height(natural_width=natural_width, natural_height=natural_height, target_width=target) == expected


def test_scaled_height_never_returns_zero() -> None:
    assert scaled_height(natural_width=10000, natural_height=1, target_width=1) == 1


def test_diagnostic_codes_share_the_image_namespace() -> None:
    assert IMAGE_BACKEND_MISSING == "maatlog.image.backend-missing"
    assert IMAGE_CODEC_MISSING == "maatlog.image.codec-missing"
    assert IMAGE_DECODE_FAILED == "maatlog.image.decode-failed"
    assert IMAGE_ENCODE_FAILED == "maatlog.image.encode-failed"
    assert IMAGE_TOO_LARGE == "maatlog.image.too-large"
    assert IMAGE_CACHE_UNWRITABLE == "maatlog.image.cache-unwritable"


def test_image_processing_error_carries_a_diagnostic() -> None:
    diagnostic = Diagnostic(code=IMAGE_DECODE_FAILED, message="Cannot decode image", source="posts/a.rst")
    error = ImageProcessingError(diagnostic)
    assert error.diagnostic is diagnostic
    assert str(error) == format_diagnostic(diagnostic)


def test_probe_and_variant_records_are_picklable() -> None:
    probe = SourceImageProbe(
        image_format=ImageFormat.JPEG, width=1600, height=900, is_multi_frame=False, has_alpha=False
    )
    variant = GeneratedVariant(
        width=480,
        height=270,
        image_format=ImageFormat.JPEG,
        cache_path=Path("/cache/ab/abcdef.jpg"),
        public_basename="hero-480w-0123456789abcdef.jpg",
        byte_size=1234,
    )
    assert pickle.loads(pickle.dumps(probe)) == probe
    assert pickle.loads(pickle.dumps(variant)) == variant


def test_variant_request_is_a_frozen_record(tmp_path: Path) -> None:
    request = VariantRequest(
        source_path=tmp_path / "hero.jpg",
        identity=IDENTITY,
        probe=SourceImageProbe(
            image_format=ImageFormat.JPEG, width=1600, height=900, is_multi_frame=False, has_alpha=False
        ),
        width=480,
        cache_root=tmp_path / "cache",
    )
    with pytest.raises(AttributeError):
        request.width = 960  # type: ignore[misc]


def test_generator_protocol_is_runtime_checkable() -> None:
    class Stub:
        def describe_backend(self) -> BackendInfo:
            return BACKEND

        def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
            raise NotImplementedError

        def generate(self, request: VariantRequest) -> GeneratedVariant:
            raise NotImplementedError

    assert isinstance(Stub(), ImageVariantGenerator)


ENTRY = ResponsiveImageEntry(
    identity=IDENTITY,
    natural_width=1600,
    natural_height=900,
    image_format=ImageFormat.JPEG,
    variants=(
        ResponsiveVariant(width=480, height=270, image_format=ImageFormat.JPEG, public_basename="hero-480w-aaaa.jpg"),
        ResponsiveVariant(
            width=1600, height=900, image_format=ImageFormat.JPEG, public_basename="hero-1600w-bbbb.jpg"
        ),
    ),
)


def test_directory_names_are_pinned() -> None:
    assert RESPONSIVE_CACHE_DIRNAME == "maatlog_responsive_images"
    assert RESPONSIVE_OUTPUT_SUBDIR == "maatlog"


def test_build_view_uses_the_largest_candidate_as_src() -> None:
    view = build_responsive_image_view(ENTRY, image_root_url="../_images/maatlog/", usage=ImageUsage.POST_TOP)
    assert view.src == "../_images/maatlog/hero-1600w-bbbb.jpg"
    assert view.width == 1600
    assert view.height == 900
    assert view.usage is ImageUsage.POST_TOP
    assert view.candidates == (
        ResponsiveImageCandidate(url="../_images/maatlog/hero-480w-aaaa.jpg", width=480),
        ResponsiveImageCandidate(url="../_images/maatlog/hero-1600w-bbbb.jpg", width=1600),
    )


def test_build_view_adds_a_missing_trailing_slash() -> None:
    view = build_responsive_image_view(ENTRY, image_root_url="_images/maatlog", usage=ImageUsage.ARCHIVE_CARD)
    assert view.src == "_images/maatlog/hero-1600w-bbbb.jpg"


def test_build_view_accepts_an_empty_root() -> None:
    view = build_responsive_image_view(ENTRY, image_root_url="", usage=ImageUsage.HOME_LEAD)
    assert view.src == "hero-1600w-bbbb.jpg"


def test_build_view_percent_encodes_a_non_ascii_root() -> None:
    view = build_responsive_image_view(ENTRY, image_root_url="../記事/_images/maatlog/", usage=ImageUsage.HOME_LATEST)
    assert view.src == "../%E8%A8%98%E4%BA%8B/_images/maatlog/hero-1600w-bbbb.jpg"


def test_srcset_lists_every_candidate_with_its_real_width() -> None:
    view = build_responsive_image_view(ENTRY, image_root_url="_images/maatlog/", usage=ImageUsage.POST_REPRESENTATIVE)
    assert view.srcset == "_images/maatlog/hero-480w-aaaa.jpg 480w, _images/maatlog/hero-1600w-bbbb.jpg 1600w"


def test_build_view_sorts_candidates_by_width() -> None:
    unsorted_entry = ResponsiveImageEntry(
        identity=IDENTITY,
        natural_width=1600,
        natural_height=900,
        image_format=ImageFormat.JPEG,
        variants=(ENTRY.variants[1], ENTRY.variants[0]),
    )
    view = build_responsive_image_view(unsorted_entry, image_root_url="", usage=ImageUsage.POST_TOP)
    assert [candidate.width for candidate in view.candidates] == [480, 1600]


def test_build_view_rejects_an_entry_without_variants() -> None:
    empty = ResponsiveImageEntry(
        identity=IDENTITY,
        natural_width=1600,
        natural_height=900,
        image_format=ImageFormat.JPEG,
        variants=(),
    )
    with pytest.raises(ValueError, match="at least one variant"):
        build_responsive_image_view(empty, image_root_url="", usage=ImageUsage.POST_TOP)


def test_manifest_entries_are_picklable_and_hold_no_paths() -> None:
    manifest: dict[str, ResponsiveImageEntry] = {IDENTITY.source_relpath: ENTRY}
    restored = pickle.loads(pickle.dumps(manifest))
    assert restored == manifest
    for variant in ENTRY.variants:
        assert isinstance(variant.public_basename, str)
        assert not isinstance(variant.public_basename, Path)


def test_view_is_picklable() -> None:
    view = build_responsive_image_view(ENTRY, image_root_url="", usage=ImageUsage.POST_TOP)
    assert pickle.loads(pickle.dumps(view)) == view


class _Builder:
    def __init__(self, name: str, image_format: str = "html") -> None:
        self.name = name
        self.format = image_format


@pytest.mark.parametrize(
    ("enabled", "builder", "expected"),
    [
        (False, _Builder("html"), False),
        (True, _Builder("html"), True),
        (True, _Builder("dirhtml"), True),
        (True, _Builder("singlehtml"), False),
        (True, _Builder("text", "text"), False),
        (False, _Builder("text", "text"), False),
    ],
)
def test_responsive_images_enabled(enabled: bool, builder: object, expected: bool) -> None:
    config = MaatlogConfig.from_values({"maatlog_responsive_images": enabled})
    assert responsive_images_enabled(config, builder) is expected  # type: ignore[arg-type]

"""Probe tests for the Pillow responsive-image backend (issue #214, task 2).

Content decides, never the file extension. Every bad input -- truncated bytes,
a format mismatch, an unreadable path, a missing codec, an image over the pixel
limit -- raises :class:`ImageProcessingError` with the mapped diagnostic code;
a bad image never yields a positive probe.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from fixtures.responsive_images.helpers import make_request
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from PIL import Image
from PIL import features as pil_features

from maatlog.image_contracts import (
    IMAGE_CODEC_MISSING,
    IMAGE_DECODE_FAILED,
    IMAGE_TOO_LARGE,
    ImageFormat,
    ImageProcessingError,
    SourceImageProbe,
    sniff_source_format,
)
from maatlog.responsive_images import PillowImageVariantGenerator


def _probe(path: Path, image_format: ImageFormat) -> SourceImageProbe:
    return PillowImageVariantGenerator().probe(path, image_format=image_format)


def _save_rgb(path: Path, image_format: ImageFormat, size: tuple[int, int], orientation: int | None = None) -> None:
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    Image.new("RGB", size, "red").save(path, format=image_format.value.upper(), exif=exif)


def _single_frame_anim_webp(data: bytes) -> bytes:
    """Rebuild an animated WebP keeping only its first ANMF frame chunk."""
    chunks: list[bytes] = []
    seen_frame = False
    offset = 12
    while offset + 8 <= len(data):
        tag = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        end = offset + 8 + size + (size & 1)
        if tag == b"ANMF":
            if seen_frame:
                offset = end
                continue
            seen_frame = True
        chunks.append(data[offset:end])
        offset = end
    assert seen_frame
    body = b"".join(chunks)
    return data[:4] + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + body


def _animated_webp_bytes() -> bytes:
    first = Image.new("RGB", (8, 5), "red")
    second = Image.new("RGB", (8, 5), "blue")
    buffer = BytesIO()
    first.save(buffer, format="WEBP", save_all=True, append_images=[second], duration=100, loop=0)
    return buffer.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_content_not_extension_and_orientation(tmp_path: Path, fmt: str) -> None:
    path = tmp_path / "misleading.txt"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (8, 5), "red").save(path, format=fmt, exif=exif)
    probed = PillowImageVariantGenerator().probe(path, image_format=ImageFormat(fmt.lower()))
    assert (probed.width, probed.height) == (5, 8)
    assert not probed.is_multi_frame


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_pixel_limit_applies_to_every_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fmt: str) -> None:
    path = tmp_path / "large.bin"
    Image.new("RGB", (11, 10)).save(path, format=fmt)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().probe(path, image_format=ImageFormat(fmt.lower()))
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE


@pytest.mark.parametrize(
    ("fmt", "size"),
    [
        ("JPEG", (8, 5)),
        ("PNG", (7, 3)),
        ("WEBP", (6, 4)),
        ("JPEG", (1, 1)),
        ("PNG", (1, 1)),
        ("WEBP", (1, 1)),
    ],
)
def test_still_images_report_dimensions_and_format(tmp_path: Path, fmt: str, size: tuple[int, int]) -> None:
    path = tmp_path / f"still.{fmt.lower()}"
    Image.new("RGB", size, "red").save(path, format=fmt)
    probed = _probe(path, ImageFormat(fmt.lower()))
    assert probed.image_format is ImageFormat(fmt.lower())
    assert (probed.width, probed.height) == size
    assert probed.width > 0 and probed.height > 0
    assert not probed.is_multi_frame
    assert not probed.has_alpha


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (None, (8, 5)),
        (1, (8, 5)),
        (2, (8, 5)),
        (3, (8, 5)),
        (4, (8, 5)),
        (5, (5, 8)),
        (6, (5, 8)),
        (7, (5, 8)),
        (8, (5, 8)),
        (0, (8, 5)),
        (9, (8, 5)),
    ],
)
def test_exif_orientation_matrix(tmp_path: Path, orientation: int | None, expected: tuple[int, int]) -> None:
    path = tmp_path / "oriented.jpg"
    _save_rgb(path, ImageFormat.JPEG, (8, 5), orientation)
    probed = _probe(path, ImageFormat.JPEG)
    assert (probed.width, probed.height) == expected


def _save_rgba(path: Path) -> None:
    Image.new("RGBA", (4, 4)).save(path, format="PNG")


def _save_la(path: Path) -> None:
    Image.new("LA", (4, 4)).save(path, format="PNG")


def _save_rgb_png(path: Path) -> None:
    Image.new("RGB", (4, 4)).save(path, format="PNG")


@pytest.mark.parametrize(
    ("name", "make", "expected"),
    [
        ("rgba", _save_rgba, True),
        ("la", _save_la, True),
        ("palette-transparent", None, True),
        ("palette-opaque", None, False),
        ("rgb-trns", None, True),
        ("l-trns", None, True),
        ("rgb-plain", _save_rgb_png, False),
    ],
)
def test_has_alpha_matrix(tmp_path: Path, name: str, make: Callable[[Path], None] | None, expected: bool) -> None:
    path = tmp_path / f"{name}.png"
    if make is not None:
        make(path)
    elif name == "palette-transparent":
        paletted = Image.new("P", (4, 4))
        paletted.putpalette([index % 256 for index in range(768)])
        paletted.save(path, format="PNG", transparency=0)
    elif name == "palette-opaque":
        paletted = Image.new("P", (4, 4))
        paletted.putpalette([index % 256 for index in range(768)])
        paletted.save(path, format="PNG")
    elif name == "rgb-trns":
        Image.new("RGB", (4, 4), (255, 0, 0)).save(path, format="PNG", transparency=(255, 0, 0))
    elif name == "l-trns":
        Image.new("L", (4, 4), 128).save(path, format="PNG", transparency=128)
    else:  # pragma: no cover - parametrize names above are exhaustive
        raise AssertionError(f"unknown alpha case {name}")
    probed = _probe(path, ImageFormat.PNG)
    assert probed.has_alpha is expected


def test_rgb_jpeg_has_no_alpha(tmp_path: Path) -> None:
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (4, 4)).save(path, format="JPEG")
    assert not _probe(path, ImageFormat.JPEG).has_alpha


@pytest.mark.parametrize(
    "header",
    [
        b"GIF87a" + b"\x00" * 40,
        b"GIF89a" + b"\x00" * 40,
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"<?xml version='1.0'?><svg/>",
        b"\xef\xbb\xbf<svg/>",
        b"<!-- a comment --><svg/>",
    ],
)
def test_sniff_returns_none_for_unresizable_inputs(tmp_path: Path, header: bytes) -> None:
    path = tmp_path / "unsupported.bin"
    path.write_bytes(header)
    assert sniff_source_format(path) is None


def test_apng_is_multi_frame(tmp_path: Path) -> None:
    path = tmp_path / "animated.png"
    first = Image.new("RGB", (8, 5), "red")
    second = Image.new("RGB", (8, 5), "blue")
    first.save(path, format="PNG", save_all=True, append_images=[second])
    probed = _probe(path, ImageFormat.PNG)
    assert probed.is_multi_frame
    assert (probed.width, probed.height) == (8, 5)


def test_animated_webp_is_multi_frame(tmp_path: Path) -> None:
    path = tmp_path / "animated.webp"
    path.write_bytes(_animated_webp_bytes())
    probed = _probe(path, ImageFormat.WEBP)
    assert probed.is_multi_frame
    assert (probed.width, probed.height) == (8, 5)


def test_single_frame_animation_container_is_multi_frame(tmp_path: Path) -> None:
    reduced = _single_frame_anim_webp(_animated_webp_bytes())
    path = tmp_path / "one-frame-anim.webp"
    path.write_bytes(reduced)
    probed = _probe(path, ImageFormat.WEBP)
    assert probed.is_multi_frame
    assert (probed.width, probed.height) == (8, 5)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_truncated_files_fail_decode(tmp_path: Path, fmt: str) -> None:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, format=fmt)
    data = buffer.getvalue()
    assert len(data) > 64
    path = tmp_path / f"truncated.{fmt.lower()}"
    path.write_bytes(data[: len(data) // 2])
    assert sniff_source_format(path) is ImageFormat(fmt.lower())
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, ImageFormat(fmt.lower()))
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


@pytest.mark.parametrize(
    ("actual", "requested"),
    [
        ("PNG", ImageFormat.JPEG),
        ("JPEG", ImageFormat.PNG),
        ("WEBP", ImageFormat.JPEG),
        ("JPEG", ImageFormat.WEBP),
        ("PNG", ImageFormat.WEBP),
        ("WEBP", ImageFormat.PNG),
    ],
)
def test_format_mismatch_fails_decode(tmp_path: Path, actual: str, requested: ImageFormat) -> None:
    path = tmp_path / f"mismatch.{actual.lower()}"
    Image.new("RGB", (8, 5), "red").save(path, format=actual)
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, requested)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_missing_file_fails_decode(tmp_path: Path) -> None:
    with pytest.raises(ImageProcessingError) as caught:
        _probe(tmp_path / "does-not-exist.png", ImageFormat.PNG)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_directory_fails_decode(tmp_path: Path) -> None:
    with pytest.raises(ImageProcessingError) as caught:
        _probe(tmp_path, ImageFormat.PNG)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_none_pixel_limit_keeps_builtin_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)
    path = tmp_path / "huge.png"
    Image.new("1", (10000, 10000)).save(path, format="PNG")
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, ImageFormat.PNG)
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE
    assert Image.MAX_IMAGE_PIXELS is None


def test_bomb_warning_is_captured_not_leaked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    path = tmp_path / "large.png"
    Image.new("RGB", (11, 10)).save(path, format="PNG")
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with pytest.raises(ImageProcessingError) as caught:
            _probe(path, ImageFormat.PNG)
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE
    assert not any(issubclass(warning.category, Image.DecompressionBombWarning) for warning in recorded)


def test_bomb_error_maps_to_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    path = tmp_path / "large.png"
    Image.new("RGB", (11, 10)).save(path, format="PNG")
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, ImageFormat.PNG)
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE


def test_corrupted_animation_header_fails_decode(tmp_path: Path) -> None:
    data = bytearray(_animated_webp_bytes())
    assert len(data) > 160
    data[32:160] = b"\x00" * 128
    path = tmp_path / "corrupt-anim.webp"
    path.write_bytes(bytes(data))
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, ImageFormat.WEBP)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_truncated_animation_fails_decode(tmp_path: Path) -> None:
    data = _animated_webp_bytes()
    path = tmp_path / "truncated-anim.webp"
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, ImageFormat.WEBP)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


@pytest.mark.parametrize(
    ("fmt", "drop"),
    [
        ("JPEG", "jpg"),
        ("WEBP", "webp"),
    ],
)
def test_missing_codec_maps_to_codec_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fmt: str, drop: str
) -> None:
    path = tmp_path / f"codec.{fmt.lower()}"
    Image.new("RGB", (8, 5), "red").save(path, format=fmt)
    real_check_codec = pil_features.check_codec
    real_check_module = pil_features.check_module

    def check_codec(name: str) -> bool:
        if name == drop:
            return False
        return real_check_codec(name)

    def check_module(name: str) -> bool:
        if name == drop:
            return False
        return real_check_module(name)

    monkeypatch.setattr(pil_features, "check_codec", check_codec)
    monkeypatch.setattr(pil_features, "check_module", check_module)
    with pytest.raises(ImageProcessingError) as caught:
        _probe(path, ImageFormat(fmt.lower()))
    assert caught.value.diagnostic.code == IMAGE_CODEC_MISSING


def _drive(
    path: Path,
    *,
    sniff: Callable[[Path], ImageFormat | None],
    probe: Callable[..., SourceImageProbe],
) -> SourceImageProbe | None:
    """Test-only caller-protocol driver: ``None`` means publish the original file."""
    image_format = sniff(path)
    if image_format is None:
        return None
    found = probe(path, image_format=image_format)
    if found.is_multi_frame:
        return None
    return found


def _recording_probe(calls: list[Path]) -> Callable[..., SourceImageProbe]:
    generator = PillowImageVariantGenerator()

    def probe(path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        calls.append(path)
        return generator.probe(path, image_format=image_format)

    return probe


@pytest.mark.parametrize("header", [b"GIF89a" + b"\x00" * 40, b"<svg/>"])
def test_caller_driver_never_probes_unsupported_inputs(tmp_path: Path, header: bytes) -> None:
    path = tmp_path / "unsupported.bin"
    path.write_bytes(header)
    calls: list[Path] = []
    assert _drive(path, sniff=sniff_source_format, probe=_recording_probe(calls)) is None
    assert calls == []


def test_caller_driver_falls_back_for_animated_inputs(tmp_path: Path) -> None:
    path = tmp_path / "animated.webp"
    path.write_bytes(_animated_webp_bytes())
    calls: list[Path] = []
    assert _drive(path, sniff=sniff_source_format, probe=_recording_probe(calls)) is None
    assert calls == [path]


def test_caller_driver_returns_probe_for_still_inputs(tmp_path: Path) -> None:
    path = tmp_path / "still.png"
    Image.new("RGB", (8, 5), "red").save(path, format="PNG")
    calls: list[Path] = []
    found = _drive(path, sniff=sniff_source_format, probe=_recording_probe(calls))
    assert found is not None
    assert (found.width, found.height) == (8, 5)
    assert calls == [path]


def test_make_request_helper_builds_variant_request(tmp_path: Path) -> None:
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    path = srcdir / "photo.png"
    Image.new("RGB", (8, 5), "red").save(path, format="PNG")
    request = make_request(path, srcdir=srcdir, cache_root=tmp_path / "cache", width=8)
    assert request.source_path == path
    assert (request.probe.width, request.probe.height) == (8, 5)
    assert request.width == 8
    assert request.cache_root == tmp_path / "cache"
    assert request.identity.source_relpath == "photo.png"

"""Oriented no-upscale variant encoding tests (issue #214, task 3).

The orientation oracle below uses a hardcoded 8-direction expected-pixel table
on an asymmetric 3x2 grid, so it stays independent of the implementation's
``ImageOps.exif_transpose``: a bare width/height swap assertion could not catch
a transposed implementation. Lossy formats use large colour blocks and assert
on interior pixels away from compression boundaries.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fixtures.responsive_images.helpers import make_request
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from PIL import Image

from maatlog._responsive_image_pixels import _encode_variant, _inspect_variant
from maatlog.image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    EncoderProfile,
    ImageFormat,
    VariantRequest,
    scaled_height,
)


@pytest.mark.parametrize(
    ("orientation", "rows"),
    [
        (1, [[1, 2, 3], [4, 5, 6]]),
        (2, [[3, 2, 1], [6, 5, 4]]),
        (3, [[6, 5, 4], [3, 2, 1]]),
        (4, [[4, 5, 6], [1, 2, 3]]),
        (5, [[1, 4], [2, 5], [3, 6]]),
        (6, [[4, 1], [5, 2], [6, 3]]),
        (7, [[6, 3], [5, 2], [4, 1]]),
        (8, [[3, 6], [2, 5], [1, 4]]),
    ],
)
def test_orientation_pixels(tmp_path: Path, orientation: int, rows: list[list[int]]) -> None:
    src = tmp_path / "source.png"
    im = Image.new("L", (3, 2))
    im.putdata([1, 2, 3, 4, 5, 6])  # pyright: ignore[reportUnknownMemberType]
    exif = Image.Exif()
    exif[274] = orientation
    im.save(src, exif=exif)
    request = _request(src, tmp_path, width=len(rows[0]))
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        assert result.size == (len(rows[0]), len(rows))
        raw_pixels = result.getdata()  # pyright: ignore[reportUnknownMemberType]
        flattened: list[Any] = list(raw_pixels)  # pyright: ignore[reportArgumentType, reportUnknownVariableType]
        assert flattened == [v for row in rows for v in row]
        assert not result.getexif()


def _save_source(
    path: Path,
    image_format: ImageFormat,
    size: tuple[int, int],
    mode: str = "RGB",
    color: Any = "red",
    orientation: int | None = None,
) -> None:
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    Image.new(mode, size, color).save(path, format=image_format.value.upper(), exif=exif)


def _with_width(request: VariantRequest, width: int) -> VariantRequest:
    return replace(request, width=width)


def _request(path: Path, tmp_path: Path, width: int) -> VariantRequest:
    return make_request(path, srcdir=tmp_path, cache_root=tmp_path / "cache", width=width)


@pytest.mark.parametrize(
    ("natural_w", "natural_h"),
    [
        (1, 1),
        (7, 3),
        (479, 900),
        (480, 1),
        (481, 3),
        (1600, 900),
        (1, 900),
    ],
)
def test_output_dimensions_follow_scaled_height(tmp_path: Path, natural_w: int, natural_h: int) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (natural_w, natural_h))
    widths = sorted({w for w in (1, 7, 479, 480, 481) if w <= natural_w} | {natural_w})
    assert natural_w in widths
    for width in widths:
        request = _request(src, tmp_path, width=width)
        target = tmp_path / f"candidate-{width}.tmp"
        _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
        expected = (width, scaled_height(natural_width=natural_w, natural_height=natural_h, target_width=width))
        with Image.open(target) as result:
            result.load()
            assert result.size == expected
        assert _inspect_variant(target, image_format=ImageFormat.PNG) == expected


@pytest.mark.parametrize(
    ("natural", "target_w", "expected_h"),
    [
        ((4, 3), 2, 2),  # 3*2/4 = 1.5 ties to even 2, not 1
        ((6, 5), 3, 2),  # 5*3/6 = 2.5 ties to even 2, not 3
        ((8, 5), 4, 2),  # 5*4/8 = 2.5 ties to even 2, not 3
        ((1600, 1), 1, 1),  # round(1/1600) = 0 floors up to 1
        ((1600, 1), 800, 1),  # 800/1600 = 0.5 ties to even 0, floors up to 1
    ],
)
def test_integer_rounding_ties_and_floor(
    tmp_path: Path, natural: tuple[int, int], target_w: int, expected_h: int
) -> None:
    assert scaled_height(natural_width=natural[0], natural_height=natural[1], target_width=target_w) == expected_h
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, natural)
    request = _request(src, tmp_path, width=target_w)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.size == (target_w, expected_h)


@pytest.mark.parametrize("width", [0, 9])
def test_out_of_range_width_is_rejected(tmp_path: Path, width: int) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (8, 5))
    request = _request(src, tmp_path, width=8)
    with pytest.raises(ValueError, match="width"):
        _encode_variant(src.read_bytes(), _with_width(request, width), DEFAULT_ENCODER_PROFILE, tmp_path / "out.tmp")


def test_probe_dimensions_mismatch_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (8, 5))
    request = _request(src, tmp_path, width=8)
    wrong_probe = replace(request.probe, width=request.probe.width + 1)
    wrong_request = replace(request, probe=wrong_probe)
    with pytest.raises(ValueError, match="probe dimensions"):
        _encode_variant(src.read_bytes(), wrong_request, DEFAULT_ENCODER_PROFILE, tmp_path / "out.tmp")


def test_unknown_resample_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (8, 5))
    request = _request(src, tmp_path, width=8)
    encoder = EncoderProfile(profile_id="test", resample="bicubic")
    with pytest.raises(ValueError, match="resample"):
        _encode_variant(src.read_bytes(), request, encoder, tmp_path / "out.tmp")


@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP])
def test_save_format_explicit_despite_tmp_suffix(tmp_path: Path, image_format: ImageFormat) -> None:
    src = tmp_path / "source.bin"
    _save_source(src, image_format, (8, 5))
    request = _request(src, tmp_path, width=8)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.format == image_format.value.upper()
        assert result.size == (8, 5)


@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.WEBP])
def test_lossy_blocks_keep_colors_and_dimensions(tmp_path: Path, image_format: ImageFormat) -> None:
    stored = Image.new("RGB", (240, 120))
    left = Image.new("RGB", (120, 120), (200, 30, 30))
    right = Image.new("RGB", (120, 120), (30, 30, 200))
    stored.paste(left, (0, 0))
    stored.paste(right, (120, 0))
    src = tmp_path / "source.bin"
    stored.save(src, format=image_format.value.upper())
    request = _request(src, tmp_path, width=120)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    expected_h = scaled_height(natural_width=240, natural_height=120, target_width=120)
    with Image.open(target) as result:
        result.load()
        assert result.size == (120, expected_h)
        rgb = result.convert("RGB")
        left_center = rgb.getpixel((30, expected_h // 2))
        right_center = rgb.getpixel((90, expected_h // 2))
        assert isinstance(left_center, tuple) and isinstance(right_center, tuple)
    for channel, expected in zip(left_center, (200, 30, 30), strict=True):
        assert abs(channel - expected) <= 16
    for channel, expected in zip(right_center, (30, 30, 200), strict=True):
        assert abs(channel - expected) <= 16


@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP])
def test_oriented_lossy_keeps_dimensions_and_color(tmp_path: Path, image_format: ImageFormat) -> None:
    src = tmp_path / "source.bin"
    _save_source(src, image_format, (8, 5), color=(200, 30, 30), orientation=6)
    request = _request(src, tmp_path, width=5)
    assert (request.probe.width, request.probe.height) == (5, 8)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.size == (5, 8)
        pixel = result.convert("RGB").getpixel((2, 4))
        assert isinstance(pixel, tuple)
        assert not result.getexif()
    for channel, expected in zip(pixel, (200, 30, 30), strict=True):
        assert abs(channel - expected) <= 24


@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP])
def test_output_carries_no_exif(tmp_path: Path, image_format: ImageFormat) -> None:
    src = tmp_path / "source.bin"
    _save_source(src, image_format, (16, 10), orientation=6)
    request = _request(src, tmp_path, width=10)
    assert (request.probe.width, request.probe.height) == (10, 16)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.size == (10, 16)
        assert not result.getexif()


def _record_save_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    original = Image.Image.save

    def spy(self: Image.Image, fp: Any, format: str | None = None, **params: Any) -> None:
        seen.append({"format": format, **params})
        original(self, fp, format=format, **params)

    monkeypatch.setattr(Image.Image, "save", spy)
    return seen


def test_default_encoder_values_reach_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected_calls = {
        ImageFormat.JPEG: {
            "format": "JPEG",
            "quality": 82,
            "progressive": True,
            "optimize": True,
            "subsampling": 2,
            "exif": b"",
            "icc_profile": None,
        },
        ImageFormat.PNG: {"format": "PNG", "optimize": True, "compress_level": 9, "exif": b"", "icc_profile": None},
        ImageFormat.WEBP: {
            "format": "WEBP",
            "quality": 82,
            "method": 6,
            "alpha_quality": 100,
            "exact": True,
            "lossless": False,
            "exif": b"",
            "icc_profile": None,
        },
    }
    prepared: list[tuple[bytes, VariantRequest, Path]] = []
    for image_format in expected_calls:
        src = tmp_path / f"source-{image_format.value}.bin"
        mode = "RGBA" if image_format is ImageFormat.WEBP else "RGB"
        color: Any = (10, 20, 30, 40) if mode == "RGBA" else "red"
        _save_source(src, image_format, (8, 5), mode=mode, color=color)
        target = tmp_path / f"out-{image_format.value}.tmp"
        prepared.append((src.read_bytes(), _request(src, tmp_path, width=8), target))
    seen = _record_save_calls(monkeypatch)
    for data, request, target in prepared:
        _encode_variant(data, request, DEFAULT_ENCODER_PROFILE, target)
    assert len(seen) == len(expected_calls)
    for call, image_format in zip(seen, expected_calls, strict=True):
        for key, value in expected_calls[image_format].items():
            assert call[key] == value, (key, call.get(key), value)


@pytest.mark.parametrize("image_format", [ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP])
def test_custom_encoder_values_reach_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, image_format: ImageFormat
) -> None:
    encoder = EncoderProfile(
        profile_id="test",
        jpeg_quality=50,
        jpeg_progressive=False,
        jpeg_optimize=False,
        jpeg_subsampling=0,
        png_optimize=False,
        png_compress_level=1,
        webp_quality=50,
        webp_method=1,
        webp_alpha_quality=90,
        webp_exact=False,
    )
    src = tmp_path / "source.bin"
    mode = "RGBA" if image_format is ImageFormat.WEBP else "RGB"
    color: Any = (10, 20, 30, 40) if mode == "RGBA" else "red"
    _save_source(src, image_format, (8, 5), mode=mode, color=color)
    request = _request(src, tmp_path, width=8)
    data = src.read_bytes()
    seen = _record_save_calls(monkeypatch)
    _encode_variant(data, request, encoder, tmp_path / "candidate.tmp")
    assert len(seen) == 1
    call = seen[0]
    assert call["format"] == image_format.value.upper()
    if image_format is ImageFormat.JPEG:
        assert call["quality"] == 50
        assert call["progressive"] is False
        assert call["optimize"] is False
        assert call["subsampling"] == 0
    elif image_format is ImageFormat.PNG:
        assert call["optimize"] is False
        assert call["compress_level"] == 1
    else:
        assert call["quality"] == 50
        assert call["method"] == 1
        assert call["alpha_quality"] == 90
        assert call["exact"] is False


@pytest.mark.parametrize(
    ("image_format", "mode", "color"),
    [
        (ImageFormat.PNG, "RGB", "red"),
        (ImageFormat.PNG, "L", 128),
        (ImageFormat.PNG, "RGBA", (255, 0, 0, 128)),
        (ImageFormat.JPEG, "RGB", "red"),
        (ImageFormat.JPEG, "L", 128),
        (ImageFormat.WEBP, "RGB", "red"),
        (ImageFormat.WEBP, "RGBA", (255, 0, 0, 128)),
    ],
)
def test_modes_roundtrip(tmp_path: Path, image_format: ImageFormat, mode: str, color: Any) -> None:
    src = tmp_path / "source.bin"
    _save_source(src, image_format, (8, 5), mode=mode, color=color)
    request = _request(src, tmp_path, width=8)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.mode == mode
        assert result.size == (8, 5)


def test_encode_writes_only_target(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (8, 5))
    request = _request(src, tmp_path, width=8)
    target = tmp_path / "candidate.tmp"
    before = set(tmp_path.rglob("*"))
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    assert set(tmp_path.rglob("*")) - before == {target}


def test_inspect_returns_dimensions(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (8, 5))
    request = _request(src, tmp_path, width=4)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    expected = (4, scaled_height(natural_width=8, natural_height=5, target_width=4))
    assert _inspect_variant(target, image_format=ImageFormat.PNG) == expected


def test_inspect_rejects_format_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _save_source(src, ImageFormat.PNG, (8, 5))
    request = _request(src, tmp_path, width=8)
    target = tmp_path / "candidate.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with pytest.raises(ValueError, match="format"):
        _inspect_variant(target, image_format=ImageFormat.JPEG)


def test_inspect_rejects_corrupt_output(tmp_path: Path) -> None:
    target = tmp_path / "candidate.tmp"
    target.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    with pytest.raises(OSError):
        _inspect_variant(target, image_format=ImageFormat.JPEG)


def test_inspect_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        _inspect_variant(tmp_path / "does-not-exist.tmp", image_format=ImageFormat.PNG)

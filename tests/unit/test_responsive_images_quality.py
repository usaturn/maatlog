"""Alpha, ICC, metadata and visual-quality tests (issue #214, task 4).

Fixtures are generated with Pillow in ``tmp_path`` only; no external downloads.
Lossy formats assert on interior block centres (tolerance <= 16 per channel)
so boundary compression noise can never fail the suite. Lossless alpha values
must match exactly.
"""

from __future__ import annotations

import struct
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fixtures.responsive_images.helpers import make_request
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from PIL import Image

from maatlog._responsive_image_pixels import _encode_variant, _inspect_variant, _srgb_profile_bytes, prepare_pixels
from maatlog.image_contracts import DEFAULT_ENCODER_PROFILE, ImageFormat, VariantRequest, scaled_height


def _request(path: Path, tmp_path: Path, width: int) -> VariantRequest:
    return make_request(path, srcdir=tmp_path, cache_root=tmp_path / "cache", width=width)


def _encode_source(source_path: Path, tmp_path: Path, width: int, name: str = "candidate.tmp") -> Path:
    request = _request(source_path, tmp_path, width=width)
    target = tmp_path / name
    _encode_variant(source_path.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    return target


def _png_chunk_types(data: bytes) -> list[bytes]:
    """Parse PNG chunks by length prefix; never substring-scan the ICC payload."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    found: list[bytes] = []
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        ctype = data[offset + 4 : offset + 8]
        found.append(ctype)
        offset += 12 + length
    return found


def _webp_chunk_tags(data: bytes) -> list[bytes]:
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    end = int.from_bytes(data[4:8], "little") + 8
    offset = 12
    tags: list[bytes] = []
    while offset + 8 <= end:
        tag = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        tags.append(tag)
        offset += 8 + size + (size & 1)
    return tags


def _fixed_srgb() -> bytes:
    return _srgb_profile_bytes()


def _raw_srgb() -> bytes:
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def _flat_data(image: Image.Image) -> list[Any]:
    """Pixel values via the 12+ accessor with an 11.3-compatible fallback."""
    getter = getattr(image, "get_flattened_data", None) or image.getdata
    return list(getter())  # pyright: ignore[reportArgumentType, reportUnknownMemberType, reportUnknownVariableType]


# ---------------------------------------------------------------------------
# Fixed sRGB profile
# ---------------------------------------------------------------------------


def test_generated_srgb_profile_is_canonical_and_readable() -> None:
    from PIL import ImageCms

    profile = _srgb_profile_bytes()
    assert profile[24:36] == struct.pack(">6H", 2000, 1, 1, 0, 0, 0)
    assert profile[84:100] == bytes(16)
    parsed = ImageCms.ImageCmsProfile(BytesIO(profile))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    assert parsed.profile.xcolor_space.strip() == "RGB"  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]


def test_srgb_profile_bytes_are_stable_across_calls() -> None:
    assert _srgb_profile_bytes() == _srgb_profile_bytes()
    assert len(_srgb_profile_bytes()) == len(_raw_srgb())
    assert _srgb_profile_bytes() != _raw_srgb()  # datetime freeze changes bytes


def test_prepare_pixels_does_not_mutate_source() -> None:
    im = Image.new("P", (4, 2))
    im.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255] * 64)
    im.putdata([0, 1, 2, 3, 3, 2, 1, 0])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    before_mode = im.mode
    before_pixels = _flat_data(im)
    before_info = dict(im.info)
    out, icc = prepare_pixels(im)
    assert im.mode == before_mode
    assert _flat_data(im) == before_pixels
    assert dict(im.info) == before_info
    assert out is not im
    out.close()
    assert icc == _fixed_srgb()


def test_prepare_pixels_rgb_copy_does_not_alias_source() -> None:
    im = Image.new("RGB", (4, 4), (10, 20, 30))
    out, icc = prepare_pixels(im)
    assert out is not im
    out.info.clear()
    assert dict(im.info) == {}
    assert icc is None
    out.close()


# ---------------------------------------------------------------------------
# Alpha: RGBA / LA / tRNS
# ---------------------------------------------------------------------------


def test_png_rgba_alpha_preserved_full_width(tmp_path: Path) -> None:
    src = tmp_path / "rgba.png"
    im = Image.new("RGBA", (8, 4))
    px = im.load()
    assert px is not None
    for y in range(4):
        for x in range(8):
            px[x, y] = (200, 30, 30, 0) if (x + y) % 2 == 0 else (30, 30, 200, 255)
    # Transparent pixels carry real red, not flattened black.
    px[0, 0] = (255, 0, 0, 0)
    im.save(src, format="PNG")
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGBA"
        assert result.size == (8, 4)
        assert result.getpixel((0, 0)) == (255, 0, 0, 0)
        alpha = result.getchannel("A")
        with Image.open(src) as original:
            original.load()
            expected_alpha = original.convert("RGBA").getchannel("A")
            assert _flat_data(alpha) == _flat_data(expected_alpha)
    assert _inspect_variant(target, image_format=ImageFormat.PNG) == (8, 4)


def test_png_rgba_resized_alpha_matches_independent_lanczos(tmp_path: Path) -> None:
    src = tmp_path / "rgba.png"
    im = Image.new("RGBA", (16, 8))
    px = im.load()
    assert px is not None
    for y in range(8):
        for x in range(16):
            px[x, y] = (200, 30, 30, 0) if x < 8 else (30, 30, 200, 255)
    im.save(src, format="PNG")
    target = _encode_source(src, tmp_path, width=8)
    expected_h = scaled_height(natural_width=16, natural_height=8, target_width=8)
    with Image.open(target) as result:
        result.load()
        assert result.size == (8, expected_h)
        with Image.open(src) as original:
            original.load()
            rgba = original.convert("RGBA")
            oracle_alpha = rgba.getchannel("A").resize((8, expected_h), Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
            got_alpha = result.getchannel("A")
            for got, want in zip(_flat_data(got_alpha), _flat_data(oracle_alpha), strict=True):
                assert isinstance(got, int) and isinstance(want, int)
                assert abs(got - want) <= 1


def test_png_la_alpha_preserved(tmp_path: Path) -> None:
    src = tmp_path / "la.png"
    im = Image.new("LA", (8, 4), (128, 255))
    px = im.load()
    assert px is not None
    px[0, 0] = (200, 0)
    im.save(src, format="PNG")
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "LA"
        assert result.getpixel((0, 0)) == (200, 0)


def test_png_rgb_trns_becomes_rgba(tmp_path: Path) -> None:
    src = tmp_path / "trns-rgb.png"
    im = Image.new("RGB", (8, 4), (255, 0, 0))
    im.putpixel((1, 0), (0, 255, 0))
    buf = BytesIO()
    im.save(buf, format="PNG", transparency=(255, 0, 0))
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGBA"
        assert result.getpixel((0, 0))[3] == 0  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        assert result.getpixel((1, 0))[3] == 255  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        assert result.getpixel((0, 0))[:3] == (255, 0, 0)  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]


def test_png_l_trns_becomes_la(tmp_path: Path) -> None:
    src = tmp_path / "trns-l.png"
    im = Image.new("L", (8, 4), 128)
    im.putpixel((1, 0), 200)
    buf = BytesIO()
    im.save(buf, format="PNG", transparency=128)
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "LA"
        assert result.getpixel((0, 0)) == (128, 0)
        assert result.getpixel((1, 0)) == (200, 255)


@pytest.mark.parametrize("transparency", [1, b"\xff\x00\x80\xff"])
def test_palette_transparency_becomes_rgba(tmp_path: Path, transparency: Any) -> None:
    src = tmp_path / "palette.png"
    im = Image.new("P", (4, 1))
    im.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255] * 64)
    im.putdata([0, 1, 2, 3])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buf = BytesIO()
    im.save(buf, format="PNG", transparency=transparency)
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=4)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGBA"
        assert result.info.get("icc_profile") == _fixed_srgb()
        pixels = [result.getpixel((x, 0)) for x in range(4)]
        assert pixels[0][:3] == (255, 0, 0)  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        if isinstance(transparency, int):
            assert pixels[1][3] == 0  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
            assert pixels[0][3] == 255  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        else:
            assert pixels[0][3] == 255  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
            assert pixels[1][3] == 0  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
            assert pixels[2][3] == 128  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]


# ---------------------------------------------------------------------------
# Mode / ICC table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("image_format", "mode", "color"),
    [
        (ImageFormat.JPEG, "RGB", (200, 30, 30)),
        (ImageFormat.JPEG, "L", 128),
        (ImageFormat.PNG, "RGB", (200, 30, 30)),
        (ImageFormat.PNG, "RGBA", (200, 30, 30, 128)),
        (ImageFormat.PNG, "L", 128),
        (ImageFormat.PNG, "LA", (128, 200)),
        (ImageFormat.WEBP, "RGB", (200, 30, 30)),
        (ImageFormat.WEBP, "RGBA", (200, 30, 30, 128)),
    ],
)
def test_rgb_like_icc_preserved_byte_identical(
    tmp_path: Path, image_format: ImageFormat, mode: str, color: Any
) -> None:
    src = tmp_path / f"icc.{image_format.value}"
    Image.new(mode, (16, 10), color).save(src, format=image_format.value.upper(), icc_profile=_fixed_srgb())
    target = _encode_source(src, tmp_path, width=16)
    with Image.open(target) as result:
        result.load()
        assert result.mode == mode
        assert result.info.get("icc_profile") == _fixed_srgb()


def test_cmyk_keeps_mode_and_icc_bytes(tmp_path: Path) -> None:
    src = tmp_path / "cmyk.jpg"
    icc = _fixed_srgb()
    Image.new("CMYK", (16, 10), (0, 128, 128, 0)).save(src, format="JPEG", icc_profile=icc)
    target = _encode_source(src, tmp_path, width=16)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "CMYK"
        assert result.info.get("icc_profile") == icc


def test_cmyk_without_icc_gains_none(tmp_path: Path) -> None:
    src = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (16, 10), (0, 128, 128, 0)).save(src, format="JPEG")
    target = _encode_source(src, tmp_path, width=16)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "CMYK"
        assert result.info.get("icc_profile") is None


@pytest.mark.parametrize(
    ("image_format", "mode", "color"),
    [
        (ImageFormat.JPEG, "RGB", (200, 30, 30)),
        (ImageFormat.PNG, "RGB", (200, 30, 30)),
        (ImageFormat.WEBP, "RGB", (200, 30, 30)),
    ],
)
def test_without_icc_gains_none_except_palette(
    tmp_path: Path, image_format: ImageFormat, mode: str, color: Any
) -> None:
    src = tmp_path / f"noicc.{image_format.value}"
    Image.new(mode, (16, 10), color).save(src, format=image_format.value.upper())
    target = _encode_source(src, tmp_path, width=16)
    with Image.open(target) as result:
        result.load()
        assert result.info.get("icc_profile") is None


# ---------------------------------------------------------------------------
# Palette CMS
# ---------------------------------------------------------------------------


def test_palette_without_icc_treated_as_srgb(tmp_path: Path) -> None:
    from PIL import ImageCms

    src = tmp_path / "p.png"
    im = Image.new("P", (8, 4))
    im.putpalette([200, 30, 30, 30, 200, 30, 30, 30, 200] * 85 + [0])
    im.putdata([(x + y) % 3 for y in range(4) for x in range(8)])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    im.save(src, format="PNG")
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGB"
        out_icc = result.info.get("icc_profile")
        assert out_icc == _fixed_srgb()
        assert isinstance(out_icc, bytes)
        parsed = ImageCms.ImageCmsProfile(BytesIO(out_icc))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        assert parsed.profile.xcolor_space.strip() == "RGB"  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
        assert result.getpixel((0, 0))[:3] == (200, 30, 30)  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]


def test_palette_with_icc_converted_and_relabelled_srgb(tmp_path: Path) -> None:
    from PIL import ImageCms

    src = tmp_path / "p-icc.png"
    raw_icc = _raw_srgb()
    assert raw_icc != _fixed_srgb()
    im = Image.new("P", (8, 4))
    im.putpalette([200, 30, 30, 30, 200, 30, 30, 30, 200] * 85 + [0])
    im.putdata([(x + y) % 3 for y in range(4) for x in range(8)])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buf = BytesIO()
    im.save(buf, format="PNG", icc_profile=raw_icc)
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGB"
        assert result.info.get("icc_profile") == _fixed_srgb()
        # Oracle: RGB palette values through sRGB -> fixed-sRGB CMS.
        with Image.open(src) as original:
            original.load()
            rgb = original.convert("RGB")
            oracle = ImageCms.profileToProfile(  # pyright: ignore[reportUnknownMemberType]
                rgb,
                ImageCms.ImageCmsProfile(BytesIO(raw_icc)),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                ImageCms.ImageCmsProfile(BytesIO(_fixed_srgb())),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,  # pyright: ignore[reportUnknownMemberType]
                outputMode="RGB",
                flags=0,  # pyright: ignore[reportArgumentType]
            )
            assert oracle is not None
            assert _flat_data(result) == _flat_data(oracle)


def test_palette_alpha_survives_cms_conversion(tmp_path: Path) -> None:
    src = tmp_path / "p-alpha.png"
    im = Image.new("P", (4, 1))
    im.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255] * 64)
    im.putdata([0, 1, 2, 3])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buf = BytesIO()
    im.save(buf, format="PNG", transparency=bytes([255, 0, 128, 255]), icc_profile=_raw_srgb())
    src.write_bytes(buf.getvalue())
    with Image.open(src) as original:
        original.load()
        expected_alpha = _flat_data(original.convert("RGBA").getchannel("A"))
    target = _encode_source(src, tmp_path, width=4)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGBA"
        assert _flat_data(result.getchannel("A")) == expected_alpha


def test_pa_mode_prepare_pixels_direct() -> None:
    from PIL import ImageCms

    im = Image.new("PA", (2, 1), (0, 255))
    im.putpalette([255, 0, 0, 0, 255, 0] + [0] * (768 - 6))
    out, icc = prepare_pixels(im)
    try:
        assert out.mode == "RGBA"
        assert icc == _fixed_srgb()
        assert isinstance(icc, bytes)
        parsed = ImageCms.ImageCmsProfile(BytesIO(icc))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        assert parsed.profile.xcolor_space.strip() == "RGB"  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    finally:
        out.close()


def test_corrupt_icc_requiring_cms_raises(tmp_path: Path) -> None:
    src = tmp_path / "p-bad-icc.png"
    im = Image.new("P", (4, 4))
    im.putpalette([255, 0, 0] * 256)
    buf = BytesIO()
    im.save(buf, format="PNG", icc_profile=b"not-an-icc")
    src.write_bytes(buf.getvalue())
    request = _request(src, tmp_path, width=4)
    with pytest.raises(OSError):
        _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, tmp_path / "out.tmp")


def test_corrupt_icc_with_unchanged_mode_copied_verbatim(tmp_path: Path) -> None:
    src = tmp_path / "rgb-bad-icc.png"
    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG", icc_profile=b"not-an-icc")
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "RGB"
        assert result.info.get("icc_profile") == b"not-an-icc"


def test_palette_without_lcms_raises_but_rgb_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import features

    real_check = features.check_module

    def fake_check(name: str) -> bool:
        if name == "littlecms2":
            return False
        return bool(real_check(name))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

    monkeypatch.setattr(features, "check_module", fake_check)
    src_p = tmp_path / "p.png"
    im = Image.new("P", (4, 4))
    im.putpalette([255, 0, 0] * 256)
    im.save(src_p, format="PNG")
    with pytest.raises(RuntimeError):
        _encode_variant(
            src_p.read_bytes(),
            _request(src_p, tmp_path, width=4),
            DEFAULT_ENCODER_PROFILE,
            tmp_path / "p-out.tmp",
        )
    src_rgb = tmp_path / "rgb.png"
    Image.new("RGB", (4, 4), (200, 30, 30)).save(src_rgb, format="PNG")
    target = tmp_path / "rgb-out.tmp"
    _encode_variant(src_rgb.read_bytes(), _request(src_rgb, tmp_path, width=4), DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.size == (4, 4)


# ---------------------------------------------------------------------------
# 1-bit / 16-bit
# ---------------------------------------------------------------------------


def test_1bit_becomes_l(tmp_path: Path) -> None:
    src = tmp_path / "one.png"
    im = Image.new("1", (8, 8), 1)
    im.putpixel((0, 0), 0)
    im.save(src, format="PNG")
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "L"
        assert result.getpixel((0, 0)) == 0
        assert result.getpixel((1, 0)) == 255


def test_1bit_trns_becomes_la_with_real_alpha(tmp_path: Path) -> None:
    src = tmp_path / "one-t.png"
    im = Image.new("1", (8, 4))
    im.putdata([0 if x < 4 else 1 for _row in range(4) for x in range(8)])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buffer = BytesIO()
    im.save(buffer, format="PNG", transparency=0)
    src.write_bytes(buffer.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "LA"
        assert result.getpixel((0, 0)) == (0, 0)  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        assert result.getpixel((7, 0)) == (255, 255)  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
    narrow = _encode_source(src, tmp_path, width=4, name="one-t-narrow.tmp")
    expected_h = scaled_height(natural_width=8, natural_height=4, target_width=4)
    with Image.open(narrow) as result:
        result.load()
        assert result.mode == "LA"
        assert result.size == (4, expected_h)
        assert result.getpixel((0, 0))[1] == 0  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        assert result.getpixel((3, 0))[1] == 255  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]


def test_16bit_gray_keeps_icc(tmp_path: Path) -> None:
    src = tmp_path / "gray16-icc.png"
    im = Image.new("I;16", (8, 4))
    im.putdata([(x * 1000) % 65536 for _row in range(4) for x in range(8)])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buf = BytesIO()
    im.save(buf, format="PNG", icc_profile=_fixed_srgb())
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "I;16"
        assert result.info.get("icc_profile") == _fixed_srgb()


def test_16bit_gray_precision_kept(tmp_path: Path) -> None:
    src = tmp_path / "gray16.png"
    im = Image.new("I;16", (8, 4))
    im.putdata([(x * 1000 + y * 5000) % 65536 for y in range(4) for x in range(8)])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buf = BytesIO()
    im.save(buf, format="PNG")
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "I;16"
        assert _flat_data(result) == _flat_data(im)


def test_16bit_trns_quantization_and_alpha_distinction(tmp_path: Path) -> None:
    src = tmp_path / "gray16t.png"
    # 256 and 257 both round to 8-bit lightness 1 yet must differ in alpha.
    values = [256, 257, 1000, 2000]
    im = Image.new("I;16", (4, 1))
    im.putdata(values)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    buf = BytesIO()
    im.save(buf, format="PNG", transparency=256)
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=4)
    with Image.open(target) as result:
        result.load()
        assert result.mode == "LA"
        assert result.getpixel((0, 0)) == (round(256 / 257), 0)
        assert result.getpixel((1, 0)) == (round(257 / 257), 255)
        assert result.getpixel((0, 0))[0] == result.getpixel((1, 0))[0]  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        assert result.getpixel((0, 0))[1] != result.getpixel((1, 0))[1]  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
        assert result.getpixel((2, 0)) == (round(1000 / 257), 255)


# ---------------------------------------------------------------------------
# Metadata stripping
# ---------------------------------------------------------------------------


def _save_jpeg_with_metadata(path: Path, *, icc: bytes | None) -> None:
    im = Image.new("RGB", (32, 20), (200, 30, 30))
    exif = Image.Exif()
    exif[274] = 1
    exif[271] = "Make"
    exif[34853] = {0: b"\x02\x03\x00\x00", 1: "N", 2: (35.0, 139.0)}
    extra: dict[str, Any] = {"exif": exif, "comment": b"secret-comment", "xmp": b"<x:xmp>data</x:xmp>"}
    if icc is not None:
        extra["icc_profile"] = icc
    im.save(path, format="JPEG", **extra)


def _save_png_with_metadata(path: Path, *, icc: bytes | None) -> None:
    from PIL.PngImagePlugin import PngInfo

    im = Image.new("RGB", (32, 20), (200, 30, 30))
    exif = Image.Exif()
    exif[271] = "Make"
    info = PngInfo()
    info.add_text("Title", "secret-title")
    info.add_text("Description", "secret-desc")
    info.add_itxt("XML:com.adobe.xmp", "<x:xmp>data</x:xmp>")
    extra: dict[str, Any] = {"exif": exif, "pnginfo": info}
    if icc is not None:
        extra["icc_profile"] = icc
    im.save(path, format="PNG", **extra)


def _save_webp_with_metadata(path: Path, *, icc: bytes | None) -> None:
    im = Image.new("RGB", (32, 20), (200, 30, 30))
    exif = Image.Exif()
    exif[271] = "Make"
    extra: dict[str, Any] = {"exif": exif, "xmp": b"<x:xmp>data</x:xmp>"}
    if icc is not None:
        extra["icc_profile"] = icc
    im.save(path, format="WEBP", **extra)


@pytest.mark.parametrize(
    ("saver", "suffix", "image_format"),
    [
        (_save_jpeg_with_metadata, "jpg", ImageFormat.JPEG),
        (_save_png_with_metadata, "png", ImageFormat.PNG),
        (_save_webp_with_metadata, "webp", ImageFormat.WEBP),
    ],
)
@pytest.mark.parametrize("with_icc", [True, False])
def test_all_candidates_strip_metadata_keep_only_icc(
    tmp_path: Path, saver: Any, suffix: str, image_format: ImageFormat, with_icc: bool
) -> None:
    src = tmp_path / f"meta.{suffix}"
    icc = _fixed_srgb() if with_icc else None
    saver(src, icc=icc)
    for width in (16, 32):
        target = tmp_path / f"out-{suffix}-{with_icc}-{width}.tmp"
        request = _request(src, tmp_path, width=width)
        _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
        with Image.open(target) as result:
            result.load()
            assert not result.getexif()
            assert result.info.get("comment") is None
            assert result.info.get("xmp") is None
            assert getattr(result, "text", {}) == {} or not getattr(result, "text", {})
            if with_icc:
                assert result.info.get("icc_profile") == _fixed_srgb()
            else:
                # Palette alone may add sRGB; RGB sources must not gain one.
                assert result.info.get("icc_profile") is None
        raw = target.read_bytes()
        if image_format is ImageFormat.PNG:
            chunks = _png_chunk_types(raw)
            assert b"tEXt" not in chunks
            assert b"zTXt" not in chunks
            assert b"iTXt" not in chunks
            assert b"eXIf" not in chunks
        elif image_format is ImageFormat.WEBP:
            tags = _webp_chunk_tags(raw)
            assert b"EXIF" not in tags
            assert b"XMP " not in tags
        assert _inspect_variant(target, image_format=image_format) is not None


def test_oriented_source_strips_exif_and_gps(tmp_path: Path) -> None:
    src = tmp_path / "orient.jpg"
    im = Image.new("RGB", (16, 10), (200, 30, 30))
    exif = Image.Exif()
    exif[274] = 6
    exif[271] = "Make"
    exif[34853] = {0: b"\x02\x03\x00\x00", 1: "N", 2: (35.0, 139.0)}
    im.save(src, format="JPEG", exif=exif)
    request = _request(src, tmp_path, width=5)
    assert (request.probe.width, request.probe.height) == (10, 16)
    target = tmp_path / "out.tmp"
    _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
    with Image.open(target) as result:
        result.load()
        assert result.size == (5, 8)
        assert not result.getexif()
        assert result.info.get("xmp") is None


def test_webp_emits_no_empty_exif_chunk(tmp_path: Path) -> None:
    src = tmp_path / "clean.webp"
    Image.new("RGB", (16, 10), (200, 30, 30)).save(src, format="WEBP")
    target = _encode_source(src, tmp_path, width=16)
    with Image.open(target) as result:
        result.load()
        assert not result.getexif()
        assert result.info.get("exif") is None
    assert b"EXIF" not in _webp_chunk_tags(target.read_bytes())


def test_png_parser_ignores_icc_payload_strings(tmp_path: Path) -> None:
    src = tmp_path / "coincide.png"
    fake_icc = b"\x00" * 64 + b"tEXt(iTXt)eXIf" + b"\x00" * 64
    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG", icc_profile=fake_icc)
    src.write_bytes(buf.getvalue())
    target = _encode_source(src, tmp_path, width=8)
    # Length-prefixed parsing sees only the real iCCP chunk, not payload text.
    assert _png_chunk_types(target.read_bytes()) == [b"IHDR", b"iCCP", b"IDAT", b"IEND"]
    with Image.open(target) as result:
        result.load()
        assert result.info.get("icc_profile") == fake_icc
    assert _inspect_variant(target, image_format=ImageFormat.PNG) == (8, 8)


def test_inspect_rejects_metadata_bearing_output(tmp_path: Path) -> None:
    from PIL.PngImagePlugin import PngInfo

    target = tmp_path / "dirty.tmp"
    info = PngInfo()
    info.add_text("Title", "secret")
    Image.new("RGB", (8, 8), (200, 30, 30)).save(target, format="PNG", pnginfo=info)
    with pytest.raises(ValueError, match="[Mm]etadata|text|EXIF|XMP"):
        _inspect_variant(target, image_format=ImageFormat.PNG)


def test_sibling_candidates_are_independent(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    Image.new("RGB", (16, 10), (200, 30, 30)).save(src, format="PNG", icc_profile=_fixed_srgb())
    before = src.read_bytes()
    first = _encode_source(src, tmp_path, width=16, name="first.tmp")
    second = _encode_source(src, tmp_path, width=8, name="second.tmp")
    assert src.read_bytes() == before
    with Image.open(first) as a, Image.open(second) as b:
        a.load()
        b.load()
        assert a.size == (16, 10)
        assert b.size == (8, scaled_height(natural_width=16, natural_height=10, target_width=8))
        assert a.info.get("icc_profile") == _fixed_srgb()


# ---------------------------------------------------------------------------
# Visual quality (temporary artifacts, recorded in the task report)
# ---------------------------------------------------------------------------


def test_visual_color_blocks_within_tolerance(tmp_path: Path) -> None:
    """Red/blue colour blocks: block-centre error <= 16 per channel (JPEG/WebP)."""
    stored = Image.new("RGB", (240, 120))
    stored.paste(Image.new("RGB", (120, 120), (200, 30, 30)), (0, 0))
    stored.paste(Image.new("RGB", (120, 120), (30, 30, 200)), (120, 0))
    for image_format in (ImageFormat.JPEG, ImageFormat.WEBP):
        src = tmp_path / f"blocks.{image_format.value}"
        stored.save(src, format=image_format.value.upper())
        target = tmp_path / f"blocks-out-{image_format.value}.tmp"
        request = _request(src, tmp_path, width=120)
        _encode_variant(src.read_bytes(), request, DEFAULT_ENCODER_PROFILE, target)
        expected_h = scaled_height(natural_width=240, natural_height=120, target_width=120)
        with Image.open(target) as result:
            result.load()
            assert result.size == (120, expected_h)
            rgb = result.convert("RGB")
            left = rgb.getpixel((30, expected_h // 2))
            right = rgb.getpixel((90, expected_h // 2))
            assert isinstance(left, tuple) and isinstance(right, tuple)
        for channel, want in zip(left, (200, 30, 30), strict=True):
            assert abs(channel - want) <= 16
        for channel, want in zip(right, (30, 30, 200), strict=True):
            assert abs(channel - want) <= 16


def test_visual_gradient_checkerboard_and_cmyk(tmp_path: Path) -> None:
    """Gradient (PNG lossless), alpha checkerboard (exact alpha), CMYK (mode)."""
    grad = Image.new("RGB", (64, 16))
    px = grad.load()
    assert px is not None
    for x in range(64):
        for y in range(16):
            px[x, y] = (x * 4 - 1 if x * 4 > 0 else 0, 100, 200 - x * 3)
    src_g = tmp_path / "gradient.png"
    grad.save(src_g, format="PNG")
    out_g = _encode_source(src_g, tmp_path, width=64, name="grad.tmp")
    with Image.open(out_g) as result:
        result.load()
        assert result.size == (64, 16)
        assert result.convert("RGB").getpixel((32, 8)) == grad.getpixel((32, 8))

    checker = Image.new("RGBA", (16, 16))
    pxc = checker.load()
    assert pxc is not None
    for y in range(16):
        for x in range(16):
            pxc[x, y] = (200, 30, 30, 255) if (x // 4 + y // 4) % 2 == 0 else (30, 30, 200, 0)
    src_c = tmp_path / "checker.png"
    checker.save(src_c, format="PNG")
    out_c = _encode_source(src_c, tmp_path, width=16, name="checker.tmp")
    with Image.open(out_c) as result:
        result.load()
        assert result.mode == "RGBA"
        assert _flat_data(result.getchannel("A")) == _flat_data(checker.getchannel("A"))

    src_k = tmp_path / "cmyk.jpg"
    cmyk = Image.new("CMYK", (64, 32), (0, 200, 200, 0))
    cmyk.save(src_k, format="JPEG")
    out_k = _encode_source(src_k, tmp_path, width=32, name="cmyk.tmp")
    with Image.open(out_k) as result:
        result.load()
        assert result.mode == "CMYK"
        assert result.size == (32, scaled_height(natural_width=64, natural_height=32, target_width=32))


def test_request_width_validation_still_holds(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    Image.new("RGB", (8, 5), (200, 30, 30)).save(src, format="PNG")
    request = _request(src, tmp_path, width=8)
    with pytest.raises(ValueError, match="width"):
        _encode_variant(src.read_bytes(), replace(request, width=0), DEFAULT_ENCODER_PROFILE, tmp_path / "o.tmp")

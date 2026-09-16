"""Oriented, exactly-sized variant encoding with fixed encoder settings.

Private pixel pipeline for the Pillow responsive-image backend (issue #214,
task 4). Decodes source bytes, bakes EXIF orientation into the pixels,
normalises mode/alpha/ICC via :func:`prepare_pixels`, resizes without ever
upscaling, strips metadata, and saves with the fixed encoder profile to the
caller-provided unique temporary path. Plain exceptions propagate: task 5
classifies them at the cache/generate boundary.
"""

from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from .image_contracts import EncoderProfile, ImageFormat, VariantRequest, scaled_height

if TYPE_CHECKING:
    from PIL import Image as PillowImageModule

__all__ = ["_encode_variant", "_inspect_variant", "_srgb_profile_bytes", "prepare_pixels"]

#: Explicit Pillow save format names, so the ``.tmp`` suffix never decides.
_SAVE_FORMAT_NAMES: Final = {
    ImageFormat.JPEG: "JPEG",
    ImageFormat.PNG: "PNG",
    ImageFormat.WEBP: "WEBP",
}

#: PNG chunk types that must never appear in a variant; the ICC lives in
#: ``iCCP`` alone. Parsed by length prefix so coincidental strings inside the
#: ICC payload are never mistaken for metadata.
_FORBIDDEN_PNG_CHUNKS: Final = frozenset({b"tEXt", b"zTXt", b"iTXt", b"eXIf"})

#: WebP RIFF chunk tags that must never appear in a variant (ICC uses ``ICCP``).
_FORBIDDEN_WEBP_CHUNKS: Final = frozenset({b"EXIF", b"XMP "})


def _srgb_profile_bytes() -> bytes:
    import struct

    from PIL import ImageCms

    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    data[24:36] = struct.pack(">6H", 2000, 1, 1, 0, 0, 0)
    data[84:100] = bytes(16)
    return bytes(data)


def prepare_pixels(image: PillowImageModule.Image) -> tuple[PillowImageModule.Image, bytes | None]:
    """Normalise *image* (already EXIF-transposed) for encoding.

    Expands palette and ``tRNS`` transparency to real alpha before any resize,
    converts palette colour through LittleCMS to the fixed sRGB profile, and
    splits out the ICC bytes to re-attach at save time. Modes that need no
    conversion keep their mode with byte-identical ICC.

    Never mutates *image*: conversions return new images and the passthrough
    path returns a copy, so clearing the result never touches the source.
    Corrupt ICC bytes that must be interpreted (palette CMS) raise; ICC kept
    with an unchanged mode is copied without interpretation.
    """
    raw_icc = image.info.get("icc_profile")
    icc: bytes | None = raw_icc if isinstance(raw_icc, bytes) else None
    mode = image.mode
    if mode == "1":
        if "transparency" in image.info:
            return _expand_1bit_trns(image, icc)
        return (image.convert("L"), icc)
    if mode in ("P", "PA"):
        return _convert_palette(image, icc)
    if mode == "I;16" and "transparency" in image.info:
        return _expand_gray16_trns(image, icc)
    if mode == "RGB" and "transparency" in image.info:
        return (image.convert("RGBA"), icc)
    if mode == "L" and "transparency" in image.info:
        return (image.convert("LA"), icc)
    return (image.copy(), icc)


def _convert_palette(
    image: PillowImageModule.Image, icc: bytes | None
) -> tuple[PillowImageModule.Image, bytes | None]:
    """Convert palette image to ``RGB`` (opaque) or ``RGBA`` via LittleCMS."""
    from PIL import ImageCms, features

    if not features.check_module("littlecms2"):  # pyright: ignore[reportUnknownMemberType]
        raise RuntimeError("littlecms2 is not available for palette conversion")
    rgba = image.convert("RGBA")
    try:
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        try:
            src_profile: Any  # pyright: ignore[reportUnknownVariableType]
            if icc is not None:
                src_profile = ImageCms.ImageCmsProfile(BytesIO(icc))  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            else:
                src_profile = ImageCms.createProfile(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                    "sRGB"
                )
            dst_profile = ImageCms.ImageCmsProfile(BytesIO(_srgb_profile_bytes()))
            try:
                converted = ImageCms.profileToProfile(  # pyright: ignore[reportUnknownMemberType]
                    rgb,
                    src_profile,  # pyright: ignore[reportUnknownArgumentType]
                    dst_profile,  # pyright: ignore[reportUnknownArgumentType]
                    renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,  # pyright: ignore[reportUnknownMemberType]
                    outputMode="RGB",
                    flags=0,  # pyright: ignore[reportArgumentType]
                )
            except ImageCms.PyCMSError as exc:
                raise ValueError(f"palette CMS transform failed: {exc}") from exc
            assert converted is not None
        finally:
            rgb.close()
        if image.mode == "PA" or "transparency" in image.info:
            converted.putalpha(alpha)
            alpha.close()
            return (converted, _srgb_profile_bytes())
        alpha.close()
        return (converted, _srgb_profile_bytes())
    finally:
        rgba.close()


def _expand_gray16_trns(
    image: PillowImageModule.Image, icc: bytes | None
) -> tuple[PillowImageModule.Image, bytes | None]:
    """Expand 16-bit grayscale ``tRNS`` to 8-bit ``LA`` with explicit quantisation.

    Compares the pre-rounding 16-bit value against the transparent value and
    emits lightness ``round(value / 257)`` with alpha 0/255. Pillow's own
    ``convert("LA")`` loses both the transparency and the lightness here, so
    the pixels are built explicitly.
    """
    from PIL import Image

    transparent = image.info.get("transparency")
    if not isinstance(transparent, int):
        return (image.copy(), icc)
    getter = getattr(image, "get_flattened_data", None) or image.getdata
    raw_values = getter()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    values: list[int] = [int(v) for v in raw_values]  # pyright: ignore[reportArgumentType, reportUnknownArgumentType, reportUnknownVariableType]
    pixels = [(round(value / 257), 0 if value == transparent else 255) for value in values]
    out = Image.new("LA", image.size)
    out.putdata(pixels)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return (out, icc)


def _expand_1bit_trns(
    image: PillowImageModule.Image, icc: bytes | None
) -> tuple[PillowImageModule.Image, bytes | None]:
    """Expand 1-bit ``tRNS`` to ``LA`` comparing pre-conversion values.

    Pillow scales 1-bit samples to 0/255 on load, including the ``tRNS`` value
    in ``info["transparency"]``, so comparing before any conversion keeps the
    transparent value distinct from its neighbour. Pixels are built explicitly
    like the 16-bit path instead of relying on ``convert``; the ICC bytes pass
    through unchanged.
    """
    from PIL import Image

    transparent = image.info.get("transparency")
    if not isinstance(transparent, int):
        return (image.convert("L"), icc)
    getter = getattr(image, "get_flattened_data", None) or image.getdata
    raw_values = getter()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    values: list[int] = [int(v) for v in raw_values]  # pyright: ignore[reportArgumentType, reportUnknownArgumentType, reportUnknownVariableType]
    pixels = [(value, 0 if value == transparent else 255) for value in values]
    out = Image.new("LA", image.size)
    out.putdata(pixels)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return (out, icc)


def _encode_variant(source_bytes: bytes, request: VariantRequest, encoder: EncoderProfile, target: Path) -> None:
    """Encode one variant to *target* (a caller-owned unique temp path).

    Raises ``ValueError`` for an unsupported ``encoder.resample``, a request
    width outside ``1..probe.width`` (MaatLog never upscales), and a decoded
    pixel size that no longer matches the probe dimensions.
    """
    from PIL import Image, ImageOps

    if encoder.resample != "lanczos":
        raise ValueError(f"unsupported resample {encoder.resample!r}")
    if request.width < 1 or request.width > request.probe.width:
        raise ValueError(f"request width {request.width} outside 1..{request.probe.width}")
    height = scaled_height(
        natural_width=request.probe.width,
        natural_height=request.probe.height,
        target_width=request.width,
    )
    with Image.open(BytesIO(source_bytes)) as source:
        source.load()
        transposed = ImageOps.exif_transpose(source)
        prepared, icc_bytes = prepare_pixels(transposed)
        if prepared is not transposed:
            transposed.close()
        pixels = prepared
    try:
        if pixels.size != (request.probe.width, request.probe.height):
            raise ValueError("probe dimensions changed")
        if request.width != pixels.width:
            resized = pixels.resize(  # pyright: ignore[reportUnknownMemberType]
                (request.width, height), Image.Resampling.LANCZOS
            )
            pixels.close()
            pixels = resized
        pixels.info.clear()
        pixels.getexif().clear()
        image_format = request.probe.image_format
        save_format = _SAVE_FORMAT_NAMES[image_format]
        if image_format is ImageFormat.JPEG:
            pixels.save(
                target,
                format=save_format,
                quality=encoder.jpeg_quality,
                progressive=encoder.jpeg_progressive,
                optimize=encoder.jpeg_optimize,
                subsampling=encoder.jpeg_subsampling,
                exif=b"",
                icc_profile=icc_bytes,
            )
        elif image_format is ImageFormat.PNG:
            pixels.save(
                target,
                format=save_format,
                optimize=encoder.png_optimize,
                compress_level=encoder.png_compress_level,
                exif=b"",
                icc_profile=icc_bytes,
            )
        elif image_format is ImageFormat.WEBP:
            pixels.save(
                target,
                format=save_format,
                quality=encoder.webp_quality,
                method=encoder.webp_method,
                alpha_quality=encoder.webp_alpha_quality,
                exact=encoder.webp_exact,
                lossless=False,
                exif=b"",
                icc_profile=icc_bytes,
            )
        else:  # pragma: no cover - ImageFormat has exactly three members
            raise ValueError(f"unsupported image format {image_format!r}")
    finally:
        pixels.close()


def _png_chunk_types(data: bytes) -> list[bytes]:
    """List PNG chunk types by length prefix; never substring-scan payloads."""
    types: list[bytes] = []
    offset = 8
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        types.append(data[offset + 4 : offset + 8])
        offset += 12 + length
    return types


def _webp_chunk_tags(data: bytes) -> list[bytes]:
    """List WebP RIFF chunk tags along validated chunk boundaries."""
    tags: list[bytes] = []
    end = int.from_bytes(data[4:8], "little") + 8
    offset = 12
    while offset + 8 <= end and offset + 8 <= len(data):
        tag = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        tags.append(tag)
        offset += 8 + size + (size & 1)
    return tags


def _inspect_variant(path: Path, *, image_format: ImageFormat) -> tuple[int, int]:
    """Verify the encoded OUTPUT file and return its ``(width, height)``.

    Runs ``verify`` then reopens and loads, rejecting animated output, a
    format mismatch, and any surviving metadata (EXIF/GPS/XMP/text) with
    ``ValueError``. Only an ICC profile may survive. Pillow's
    decompression-bomb guard -- error and warning band alike -- is also
    reported as ``ValueError`` so a variant over a lowered site limit reads
    as a cache miss instead of leaking a raw exception or warning. Corrupt
    or missing files raise the underlying Pillow/OSError untouched.
    """
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as probe:
                probe.verify()
            with Image.open(path) as image:
                image.load()
                if bool(getattr(image, "is_animated", False)):
                    raise ValueError(f"animated output at {path}")
                n_frames = getattr(image, "n_frames", 1)
                if isinstance(n_frames, int) and n_frames > 1:
                    raise ValueError(f"multi-frame output at {path}")
                expected = _SAVE_FORMAT_NAMES[image_format]
                if image.format != expected:
                    raise ValueError(f"format {image.format!r} does not match {expected!r}")
                width, height = image.size
                if width < 1 or height < 1:
                    raise ValueError(f"invalid output dimensions {(width, height)}")
                if image.getexif():
                    raise ValueError(f"EXIF metadata present at {path}")
                if image_format is ImageFormat.PNG:
                    text = getattr(image, "text", None)
                    if text:
                        raise ValueError(f"text metadata present at {path}")
                    for key in image.info:
                        if key != "icc_profile":
                            raise ValueError(f"metadata {key!r} present at {path}")
                    raw = path.read_bytes()
                    for chunk in _png_chunk_types(raw):
                        if chunk in _FORBIDDEN_PNG_CHUNKS:
                            raise ValueError(f"metadata chunk {chunk!r} present at {path}")
                elif image_format is ImageFormat.JPEG:
                    if image.info.get("comment") is not None:
                        raise ValueError(f"comment metadata present at {path}")
                    if image.info.get("xmp") is not None:
                        raise ValueError(f"XMP metadata present at {path}")
                    if image.info.get("exif") is not None:
                        raise ValueError(f"EXIF metadata present at {path}")
                elif image_format is ImageFormat.WEBP:
                    if image.info.get("exif") is not None:
                        raise ValueError(f"EXIF metadata present at {path}")
                    if image.info.get("xmp") is not None:
                        raise ValueError(f"XMP metadata present at {path}")
                    raw = path.read_bytes()
                    for tag in _webp_chunk_tags(raw):
                        if tag in _FORBIDDEN_WEBP_CHUNKS:
                            raise ValueError(f"metadata chunk {tag!r} present at {path}")
                return (width, height)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"variant exceeds the pixel limit at {path}") from exc

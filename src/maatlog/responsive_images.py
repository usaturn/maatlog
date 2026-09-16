"""Responsive image variants generated with a lazily imported Pillow backend.

Importing this module -- and constructing :class:`PillowImageVariantGenerator`
-- never imports Pillow, so documentation builds with responsive images
disabled (the default) pay nothing for the feature. Pillow is imported only
when :meth:`PillowImageVariantGenerator.describe_backend` runs (and, in later
tasks, when probing or generating variants).
"""

from __future__ import annotations

import hashlib
import warnings
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from ._responsive_image_cache import get_or_create
from ._responsive_image_pixels import _encode_variant, _inspect_variant, prepare_pixels
from .errors import Diagnostic
from .image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    IMAGE_BACKEND_MISSING,
    IMAGE_CACHE_UNWRITABLE,
    IMAGE_CODEC_MISSING,
    IMAGE_DECODE_FAILED,
    IMAGE_ENCODE_FAILED,
    IMAGE_TOO_LARGE,
    SNIFF_HEADER_BYTES,
    BackendInfo,
    EncoderProfile,
    GeneratedVariant,
    ImageFormat,
    ImageProcessingError,
    SourceImageProbe,
    VariantRequest,
    compute_variant_key,
    scaled_height,
    sniff_image_format,
    variant_cache_relpath,
    variant_public_basename,
)

if TYPE_CHECKING:
    from PIL.ImageFile import ImageFile as PillowImage

__all__ = [
    "PIPELINE_SCHEMA",
    "PillowImageVariantGenerator",
]

#: Version of the variant pipeline this backend implements. It enters the
#: variant cache key via :class:`BackendInfo`, so bumping it here invalidates
#: every cached variant.
PIPELINE_SCHEMA: Final = 1

_BACKEND_ID: Final = "pillow"

#: Codec version placeholder when the capability exists but Pillow reports no version.
_UNKNOWN_VERSION: Final = "unavailable"

#: Codec version placeholder when the capability itself is missing.
_MISSING_CAPABILITY_VERSION: Final = "absent"

#: Own pixel ceiling, applied even when Pillow's ``MAX_IMAGE_PIXELS`` is
#: ``None`` or raised above it: a lower site-wide limit is still honoured via
#: ``min``. ``Image.MAX_IMAGE_PIXELS`` itself is never modified.
_DECODE_PIXEL_LIMIT: Final = 89_478_485

#: Pillow ``Image.format`` names this backend can probe.
_PILLOW_FORMAT_NAMES: Final = {
    "JPEG": ImageFormat.JPEG,
    "PNG": ImageFormat.PNG,
    "WEBP": ImageFormat.WEBP,
}

#: Pillow capability name guarding each probed format.
_FORMAT_CODECS: Final = {
    ImageFormat.JPEG: "jpg",
    ImageFormat.PNG: "zlib",
    ImageFormat.WEBP: "webp",
}


def _codec_missing_error(image_format: ImageFormat) -> ImageProcessingError:
    codec = _FORMAT_CODECS[image_format]
    return ImageProcessingError(
        Diagnostic(
            code=IMAGE_CODEC_MISSING,
            message=f"Responsive image backend cannot decode {image_format.value.upper()} images",
            field="image",
            value=image_format.value,
            expected=f'Install a Pillow build with {codec} support (pip install "maatlog[images]")',
        )
    )


def _littlecms2_missing_error(source: str | None) -> ImageProcessingError:
    return ImageProcessingError(
        Diagnostic(
            code=IMAGE_CODEC_MISSING,
            message="Responsive image backend cannot convert palette images without littlecms2",
            field="image",
            value="littlecms2",
            source=source,
            expected='Install a Pillow build with littlecms2 support (pip install "maatlog[images]")',
        )
    )


def _decode_failed_error(source: str | None) -> ImageProcessingError:
    return ImageProcessingError(
        Diagnostic(
            code=IMAGE_DECODE_FAILED,
            message="Source image cannot be decoded",
            source=source,
            field="image",
            expected="Use an intact source file in a supported format",
        )
    )


def _too_large_error(source: str | None, width: int | None = None, height: int | None = None) -> ImageProcessingError:
    value = f"{width}x{height} pixels" if width is not None and height is not None else None
    return ImageProcessingError(
        Diagnostic(
            code=IMAGE_TOO_LARGE,
            message="Source image exceeds the safe decode limit",
            source=source,
            field="image",
            value=value,
            expected="Use a smaller source image",
        )
    )


def _probe_failure_error(exc: Exception, source: str | None) -> ImageProcessingError:
    """Map a Pillow failure to its diagnostic.

    Bomb/size exhaustion is too-large; everything else is decode-failed.
    Callers pass the already-read *source* path (``None`` when unknown).
    """
    from PIL import Image

    if isinstance(exc, (Image.DecompressionBombError, Image.DecompressionBombWarning, MemoryError)):
        return _too_large_error(source)
    return _decode_failed_error(source)


def _encode_failed_error(source: str | None) -> ImageProcessingError:
    return ImageProcessingError(
        Diagnostic(
            code=IMAGE_ENCODE_FAILED,
            message="Image variant cannot be encoded",
            source=source,
            field="image",
            expected="Use an intact source file in a supported format",
        )
    )


def _cache_unwritable_error(target: Path) -> ImageProcessingError:
    return ImageProcessingError(
        Diagnostic(
            code=IMAGE_CACHE_UNWRITABLE,
            message="Responsive image variant cache is not writable",
            field="maatlog_responsive_images",
            value=str(target),
            expected="Make the cache directory writable and rebuild",
        )
    )


def _require_int_range(field: str, value: int, low: int, high: int) -> None:
    """Reject non-int (including bool) and out-of-range encoder values outright; never clamp."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"encoder {field} must be an int in {low}..{high}, got {value!r}")


def _require_non_empty_str(field: str, value: object) -> None:
    """Accept only a non-empty ``str``; anything else is a caller bug, not a default."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"encoder {field} must be a non-empty string, got {value!r}")


def _require_bool(field: str, value: bool) -> None:
    """Accept only real bools: ``0``/``1`` on a bool field is a caller bug, not ``False``/``True``."""
    if type(value) is not bool:
        raise ValueError(f"encoder {field} must be a bool, got {value!r}")


def _validate_encoder_profile(encoder: EncoderProfile) -> None:
    """Reject encoder settings Pillow cannot honour, before any cache write.

    Every range mirrors the encoder contract: JPEG quality 0..100,
    subsampling 0/1/2, PNG compress level 0..9, WebP quality/alpha 0..100 and
    method 0..6. Bools are allowed only on bool fields; ``profile_id`` must be
    a non-empty string. Values are never silently clamped.
    """
    _require_non_empty_str("profile_id", encoder.profile_id)
    if encoder.resample != "lanczos":
        raise ValueError(f"unsupported resample {encoder.resample!r}")
    _require_int_range("jpeg_quality", encoder.jpeg_quality, 0, 100)
    _require_bool("jpeg_progressive", encoder.jpeg_progressive)
    _require_bool("jpeg_optimize", encoder.jpeg_optimize)
    _require_int_range("jpeg_subsampling", encoder.jpeg_subsampling, 0, 2)
    _require_bool("png_optimize", encoder.png_optimize)
    _require_int_range("png_compress_level", encoder.png_compress_level, 0, 9)
    _require_int_range("webp_quality", encoder.webp_quality, 0, 100)
    _require_int_range("webp_method", encoder.webp_method, 0, 6)
    _require_int_range("webp_alpha_quality", encoder.webp_alpha_quality, 0, 100)
    _require_bool("webp_exact", encoder.webp_exact)


def _with_source(exc: ImageProcessingError, source_path: Path) -> ImageProcessingError:
    """Return *exc* carrying *source_path* when it has no source yet."""
    if exc.diagnostic.source is None:
        return ImageProcessingError(exc.diagnostic.model_copy(update={"source": str(source_path)}))
    return exc


def _webp_container_is_animated(data: bytes) -> bool:
    """Report whether a WebP RIFF container carries animation.

    Inspects ``ANIM`` chunks and the ``VP8X`` animation flag along validated
    chunk boundaries, so a single-frame animation container still counts while
    a truncated container raises ``ValueError`` instead of probing clean.
    """
    offset = 12
    end = int.from_bytes(data[4:8], "little") + 8
    if end > len(data):
        raise ValueError("truncated RIFF container")
    animated = False
    while offset + 8 <= end:
        tag = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        start = offset + 8
        if start + size > end:
            raise ValueError("truncated RIFF chunk")
        if tag == b"ANIM" or (tag == b"VP8X" and size >= 1 and data[start] & 2):
            animated = True
        offset = start + size + (size & 1)
    return animated


def _is_multi_frame(image: PillowImage, image_format: ImageFormat, container_bytes: bytes) -> bool:
    """Report whether an open image holds more than one frame.

    A one-frame animation container still counts as multi-frame; callers
    publish the original instead of generating variants from it.
    """
    if bool(getattr(image, "is_animated", False)):
        return True
    n_frames = getattr(image, "n_frames", 1)
    if isinstance(n_frames, int) and n_frames > 1:
        return True
    if image_format is ImageFormat.PNG and image.get_format_mimetype() == "image/apng":
        return True
    return image_format is ImageFormat.WEBP and _webp_container_is_animated(container_bytes)


def _oriented_dimensions(image: PillowImage, width: int, height: int) -> tuple[int, int]:
    """Apply EXIF orientation to header dimensions.

    Orientations 5-8 swap width and height; a missing tag, an unreadable EXIF
    block, or a value outside 1-8 means no rotation.
    """
    try:
        orientation = image.getexif().get(274)
    except Exception:
        return width, height
    if orientation in (5, 6, 7, 8):
        return height, width
    return width, height


def _has_alpha(image: PillowImage) -> bool:
    """Report whether an open image carries transparency.

    Any alpha band counts, as do palette transparency and the PNG ``tRNS``
    chunk Pillow exposes as ``info["transparency"]``; a bare mode comparison
    would miss all but ``RGBA``.
    """
    if "A" in image.getbands():
        return True
    return "transparency" in image.info


def _probe_open_image(image: PillowImage, image_format: ImageFormat, container_bytes: bytes) -> SourceImageProbe:
    """Probe an already-open Pillow image without touching the filesystem.

    Reads ``container_bytes`` only for the WebP animation check; everything
    else comes from *image*. Pixel-limit and Pillow bomb failures raise
    ``IMAGE_TOO_LARGE``; every other decode problem raises
    ``IMAGE_DECODE_FAILED``. Task 5 reuses this for its snapshot recheck, so it
    keeps its own warning capture instead of relying on the caller.
    """
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            pillow_format = image.format
            if pillow_format is None or _PILLOW_FORMAT_NAMES.get(pillow_format) is not image_format:
                raise _decode_failed_error(None)
            width, height = image.size
            ceiling = Image.MAX_IMAGE_PIXELS
            effective = _DECODE_PIXEL_LIMIT if ceiling is None else min(_DECODE_PIXEL_LIMIT, ceiling)
            if width * height > effective:
                raise _too_large_error(None, width, height)
            is_multi_frame = _is_multi_frame(image, image_format, container_bytes)
            if not is_multi_frame:
                image.load()
            width, height = _oriented_dimensions(image, width, height)
            if width < 1 or height < 1:
                raise _decode_failed_error(None)
            return SourceImageProbe(
                image_format=image_format,
                width=width,
                height=height,
                is_multi_frame=is_multi_frame,
                has_alpha=_has_alpha(image),
            )
    except Exception as exc:
        if isinstance(exc, ImageProcessingError):
            raise
        raise _probe_failure_error(exc, None) from exc


def _read_version(features: Any, name: str, present: bool) -> str:
    """Return Pillow's implementation version for *name*.

    ``"absent"`` when the capability itself is missing, ``"unavailable"`` when
    it exists but no version string can be read, so every backend reports all
    six codec names in a fixed shape.
    """
    if not present:
        return _MISSING_CAPABILITY_VERSION
    try:
        version = features.version(name)
    except Exception:
        return _UNKNOWN_VERSION
    return version if version else _UNKNOWN_VERSION


class PillowImageVariantGenerator:
    """Generates responsive image width variants with Pillow.

    The constructor only stores the encoder profile: it never imports Pillow,
    touches the filesystem, or inspects any image. Every Pillow import happens
    inside the method that needs it, so merely registering this backend costs a
    disabled build nothing.
    """

    def __init__(self, *, encoder: EncoderProfile = DEFAULT_ENCODER_PROFILE) -> None:
        self.encoder = encoder

    def describe_backend(self) -> BackendInfo:
        """Identify this backend precisely enough to key a cache on it.

        Raises :class:`ImageProcessingError` with
        :data:`IMAGE_BACKEND_MISSING` when Pillow cannot be imported or its
        image core cannot initialize. A missing optional capability -- a codec,
        WebP support, LittleCMS -- only shrinks ``supported_formats`` and is
        reported as ``"absent"`` in ``codec_versions``; it never fails the
        backend itself.
        """
        try:
            import PIL
            from PIL import features

            available = {
                "jpg": bool(features.check_codec("jpg")),
                "zlib": bool(features.check_codec("zlib")),
                "webp": bool(features.check_module("webp")),
                "libjpeg_turbo": bool(features.check_feature("libjpeg_turbo")),
                "zlib_ng": bool(features.check_feature("zlib_ng")),
                "littlecms2": bool(features.check_module("littlecms2")),
            }
            codec_versions = tuple(
                sorted((name, _read_version(features, name, present)) for name, present in available.items())
            )
            supported = frozenset(
                image_format
                for image_format, codec in (
                    (ImageFormat.JPEG, "jpg"),
                    (ImageFormat.PNG, "zlib"),
                    (ImageFormat.WEBP, "webp"),
                )
                if available[codec]
            )
            backend_version: str = PIL.__version__
        except (ImportError, OSError) as exc:
            raise ImageProcessingError(
                Diagnostic(
                    code=IMAGE_BACKEND_MISSING,
                    message="Responsive image backend is unavailable",
                    field="maatlog_responsive_images",
                    expected='pip install "maatlog[images]"',
                )
            ) from exc
        return BackendInfo(
            backend_id=_BACKEND_ID,
            backend_version=backend_version,
            codec_versions=codec_versions,
            supported_formats=supported,
            pipeline_schema=PIPELINE_SCHEMA,
        )

    def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        """Read dimensions and frame count without producing any output.

        Content decides, never the file extension: a sniff mismatch, an
        unreadable path, and truncated or otherwise undecodable bytes raise
        ``IMAGE_DECODE_FAILED``; an image over the pixel limit raises
        ``IMAGE_TOO_LARGE``; a format this Pillow build cannot decode raises
        ``IMAGE_CODEC_MISSING``. Only this method imports Pillow for probing;
        the constructor and module import stay Pillow-free.
        """
        if image_format not in self.describe_backend().supported_formats:
            raise _codec_missing_error(image_format)
        try:
            container = source_path.read_bytes()
        except OSError as exc:
            raise _decode_failed_error(str(source_path)) from exc
        if sniff_image_format(container[:SNIFF_HEADER_BYTES]) is not image_format:
            raise _decode_failed_error(str(source_path))
        from PIL import Image

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(BytesIO(container))
                with image:
                    try:
                        return _probe_open_image(image, image_format, container)
                    except ImageProcessingError as exc:
                        raise _with_source(exc, source_path) from exc
        except Exception as exc:
            if isinstance(exc, ImageProcessingError):
                raise
            raise _probe_failure_error(exc, str(source_path)) from exc

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        """Return the variant for *request*, reusing the cache when it is intact.

        The source bytes are read once; their SHA-256 must match
        ``request.identity`` before any cache hit is considered, and a miss
        decodes and re-probes from that same snapshot, comparing
        format, dimensions, animation and alpha against the request. The source
        is never re-opened mid-generation. A warm hit skips encoding but still
        verifies the source hash.

        ``ValueError`` means the request itself is unusable (bad width, bad
        probe dimensions, a multi-frame source, or an unencodable encoder
        profile) and is raised before any cache write. Inside the cache,
        ``ValueError`` and errno-less ``OSError`` from encoding or verification
        map to ``IMAGE_ENCODE_FAILED``, errno-bearing file I/O to
        ``IMAGE_CACHE_UNWRITABLE``, and source decode, snapshot and identity
        mismatches to ``IMAGE_DECODE_FAILED``.
        """
        probe = request.probe
        if type(probe.width) is not int or type(probe.height) is not int or probe.width < 1 or probe.height < 1:
            raise ValueError(f"probe dimensions must be positive ints, got {(probe.width, probe.height)!r}")
        if probe.is_multi_frame:
            raise ValueError("multi-frame sources are published as-is; refusing to generate a variant")
        width = request.width
        if type(width) is not int or width < 1 or width > probe.width:
            raise ValueError(f"request width must be an int in 1..{probe.width}, got {width!r}")
        _validate_encoder_profile(self.encoder)
        try:
            source_bytes = request.source_path.read_bytes()
        except OSError as exc:
            raise _decode_failed_error(str(request.source_path)) from exc
        if hashlib.sha256(source_bytes).hexdigest() != request.identity.content_hash:
            raise _decode_failed_error(str(request.source_path))
        image_format = probe.image_format
        backend = self.describe_backend()
        key = compute_variant_key(
            identity=request.identity,
            width=width,
            image_format=image_format,
            encoder=self.encoder,
            backend=backend,
        )
        target = request.cache_root / variant_cache_relpath(key, image_format)
        height = scaled_height(natural_width=probe.width, natural_height=probe.height, target_width=width)
        source_path = str(request.source_path)

        def _write(image_temp: Path) -> None:
            from PIL import Image, ImageOps

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(source_bytes)) as snapshot:
                        fresh = _probe_open_image(snapshot, image_format, source_bytes)
                        if (
                            fresh.image_format != image_format
                            or fresh.width != probe.width
                            or fresh.height != probe.height
                            or fresh.is_multi_frame
                            or fresh.has_alpha != probe.has_alpha
                        ):
                            raise _decode_failed_error(source_path)
                        transposed = ImageOps.exif_transpose(snapshot)
                        try:
                            prepared, _ = prepare_pixels(transposed)
                        except ImportError as exc:
                            raise _littlecms2_missing_error(source_path) from exc
                        except RuntimeError as exc:
                            if "littlecms2" not in str(exc):
                                raise
                            raise _littlecms2_missing_error(source_path) from exc
                        else:
                            prepared.close()
                        finally:
                            if transposed is not snapshot:
                                transposed.close()
            except ImageProcessingError as exc:
                raise _with_source(exc, request.source_path) from exc
            except (Image.DecompressionBombError, Image.DecompressionBombWarning, MemoryError) as exc:
                raise _too_large_error(source_path) from exc
            except OSError as exc:
                if exc.errno is not None:
                    raise
                raise _decode_failed_error(source_path) from exc
            except ValueError as exc:
                raise _decode_failed_error(source_path) from exc
            try:
                _encode_variant(source_bytes, request, self.encoder, image_temp)
            except ImageProcessingError:
                raise
            except ImportError as exc:
                raise _littlecms2_missing_error(source_path) from exc
            except (ValueError, RuntimeError) as exc:
                raise _encode_failed_error(source_path) from exc
            except OSError as exc:
                if exc.errno is not None:
                    raise
                raise _encode_failed_error(source_path) from exc

        def _inspect(path: Path) -> tuple[int, int]:
            return _inspect_variant(path, image_format=image_format)

        try:
            byte_size = get_or_create(
                target=target,
                key=key,
                width=width,
                height=height,
                image_format=image_format,
                write=_write,
                inspect=_inspect,
            )
        except ImageProcessingError:
            raise
        except ValueError as exc:
            raise _encode_failed_error(source_path) from exc
        except OSError as exc:
            if exc.errno is None:
                raise _encode_failed_error(source_path) from exc
            raise _cache_unwritable_error(target) from exc
        return GeneratedVariant(
            width=width,
            height=height,
            image_format=image_format,
            cache_path=target,
            public_basename=variant_public_basename(
                identity=request.identity, key=key, width=width, image_format=image_format
            ),
            byte_size=byte_size,
        )

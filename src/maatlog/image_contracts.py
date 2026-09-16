"""Shared contracts for MaatLog responsive images.

This module fixes the interface every responsive-image participant agrees on:
the formats MaatLog resizes, how a source image is identified, how a variant's
cache key and published name are derived, which widths are generated, how a
theme receives the result, and where the image backend is injected.

Nothing here imports Pillow. Importing this module must stay free of image
backend cost so that projects with responsive images disabled -- the default --
never pay for a feature they do not use.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import astuple, dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from re import compile as re_compile
from types import MappingProxyType
from typing import Final, Protocol, TypeAlias, cast, runtime_checkable
from urllib.parse import quote

from sphinx.application import Sphinx
from sphinx.builders import Builder

from .builders import is_full_html_builder
from .config import MaatlogConfig
from .errors import Diagnostic, MaatlogBuildError, format_diagnostic

__all__ = [
    "CACHE_SCHEMA_VERSION",
    "DEFAULT_ENCODER_PROFILE",
    "FORMAT_EXTENSIONS",
    "ICC_POLICY_ID",
    "IMAGE_BACKEND_MISSING",
    "IMAGE_CACHE_UNWRITABLE",
    "IMAGE_CODEC_MISSING",
    "IMAGE_DECODE_FAILED",
    "IMAGE_ENCODE_FAILED",
    "IMAGE_TOO_LARGE",
    "METADATA_POLICY_ID",
    "ORIENTATION_POLICY_ID",
    "RESPONSIVE_CACHE_DIRNAME",
    "RESPONSIVE_OUTPUT_SUBDIR",
    "SNIFF_HEADER_BYTES",
    "BackendInfo",
    "EncoderProfile",
    "GeneratedVariant",
    "ImageFetchPriority",
    "ImageFormat",
    "ImageLoading",
    "ImageProcessingError",
    "ImageUsage",
    "ImageVariantGenerator",
    "ResponsiveImageCandidate",
    "ResponsiveImageEntry",
    "ResponsiveImageManifest",
    "ResponsiveImageView",
    "ResponsiveVariant",
    "SourceImageIdentity",
    "SourceImageProbe",
    "VariantGeneratorFactory",
    "VariantRequest",
    "build_responsive_image_view",
    "build_source_identity",
    "compute_content_hash",
    "compute_variant_key",
    "register_responsive_images",
    "register_variant_generator_factory",
    "resolve_variant_generator",
    "responsive_images_enabled",
    "scaled_height",
    "select_candidate_widths",
    "sniff_image_format",
    "sniff_source_format",
    "variant_cache_relpath",
    "variant_public_basename",
]


class ImageFormat(StrEnum):
    """A raster format MaatLog resizes into width variants.

    GIF and SVG are deliberately absent: MaatLog never resizes them, so putting
    them here would create values no generator can serve. Detection returns
    ``None`` for them instead, which callers read as "publish the original".
    """

    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"


class ImageUsage(StrEnum):
    """Where a responsive image is drawn, which decides its ``sizes``.

    ``ARCHIVE_CARD`` covers both archive pages and the ``post-list`` directive:
    they share the same grid and card width in the bundled default theme.
    """

    POST_TOP = "post-top"
    POST_REPRESENTATIVE = "post-representative"
    HOME_LEAD = "home-lead"
    HOME_SECONDARY = "home-secondary"
    HOME_LATEST = "home-latest"
    ARCHIVE_CARD = "archive-card"


class ImageLoading(StrEnum):
    EAGER = "eager"
    LAZY = "lazy"


class ImageFetchPriority(StrEnum):
    HIGH = "high"
    AUTO = "auto"
    LOW = "low"


FORMAT_EXTENSIONS: Final[Mapping[ImageFormat, str]] = MappingProxyType(
    {
        ImageFormat.JPEG: ".jpg",
        ImageFormat.PNG: ".png",
        ImageFormat.WEBP: ".webp",
    }
)

#: Bytes read from a source file to identify its format. Every magic number
#: this module recognises fits well inside this window.
SNIFF_HEADER_BYTES: Final = 32

_JPEG_MAGIC: Final = b"\xff\xd8\xff"
_PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
_RIFF_MAGIC: Final = b"RIFF"
_WEBP_MAGIC: Final = b"WEBP"


def sniff_image_format(header: bytes) -> ImageFormat | None:
    """Identify a resizable raster format from *header* bytes.

    Returns ``None`` for anything MaatLog does not resize -- GIF, SVG, unknown
    formats, truncated files. That is not an error: the caller publishes the
    original image with a single ``src``.

    Content decides, never the file extension: a JPEG named ``.png`` is a JPEG.
    """
    if header.startswith(_JPEG_MAGIC):
        return ImageFormat.JPEG
    if header.startswith(_PNG_MAGIC):
        return ImageFormat.PNG
    if header[:4] == _RIFF_MAGIC and header[8:12] == _WEBP_MAGIC:
        return ImageFormat.WEBP
    return None


def sniff_source_format(path: Path) -> ImageFormat | None:
    """Identify *path* by reading only its first :data:`SNIFF_HEADER_BYTES` bytes.

    An unreadable *path* raises ``OSError``: an I/O failure is not an
    unsupported format and must not silently fall back to a single ``src``.
    """
    with path.open("rb") as stream:
        header = stream.read(SNIFF_HEADER_BYTES)
    return sniff_image_format(header)


#: Bumped when the meaning of a cache key input changes, invalidating every entry.
CACHE_SCHEMA_VERSION: Final = 1

#: EXIF orientation is baked into the pixels; the variant carries no orientation tag.
ORIENTATION_POLICY_ID: Final = "exif-transpose-1"

#: EXIF, GPS and XMP are dropped from every generated variant.
METADATA_POLICY_ID: Final = "strip-exif-gps-xmp-1"

#: An embedded ICC profile survives an unchanged colour mode; a mode conversion
#: (CMYK or palette to RGB) re-embeds sRGB instead.
ICC_POLICY_ID: Final = "preserve-or-srgb-1"

_HASH_CHUNK_BYTES: Final = 1024 * 1024
_UNSAFE_STEM_CHARS: Final = re_compile(r"[^A-Za-z0-9._-]+")
_REPEATED_DASHES: Final = re_compile(r"-{2,}")
_MAX_STEM_LENGTH: Final = 40
_KEY_PREFIX_LENGTH: Final = 16


@dataclass(frozen=True, slots=True)
class SourceImageIdentity:
    """What makes one source image distinct from another.

    Both halves matter. ``content_hash`` alone would let two documents share one
    published file, which makes per-source ownership -- and therefore safe
    cleanup of stale variants -- impossible to prove. ``source_relpath`` alone
    would reuse stale variants after an image is replaced in place.
    """

    source_relpath: str
    content_hash: str


def compute_content_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*'s bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_identity(path: Path, *, srcdir: Path) -> SourceImageIdentity:
    """Identify *path* by its srcdir-relative POSIX path and content hash.

    *path* must already have passed :func:`maatlog.images.validate_image_uri`,
    which guarantees it is an existing regular file under *srcdir*.
    """
    relative = path.resolve().relative_to(srcdir.resolve())
    return SourceImageIdentity(
        source_relpath=relative.as_posix(),
        content_hash=compute_content_hash(path),
    )


@dataclass(frozen=True, slots=True)
class EncoderProfile:
    """Fixed encoder settings shared by every generated variant.

    Every field feeds the variant cache key, so changing a value here changes
    the produced variant name even when ``profile_id`` stays the same.
    """

    profile_id: str
    resample: str = "lanczos"
    jpeg_quality: int = 82
    jpeg_progressive: bool = True
    jpeg_optimize: bool = True
    jpeg_subsampling: int = 2
    png_optimize: bool = True
    png_compress_level: int = 9
    webp_quality: int = 82
    webp_method: int = 6
    webp_alpha_quality: int = 100
    webp_exact: bool = True


DEFAULT_ENCODER_PROFILE: Final = EncoderProfile(profile_id="maatlog-encoder-1")


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Identifies the image backend precisely enough to key a cache on it.

    ``supported_formats`` is capability, not output: it never enters a cache key,
    because a backend built without WebP produces byte-identical JPEG variants
    to one built with it.
    """

    backend_id: str
    backend_version: str
    codec_versions: tuple[tuple[str, str], ...]
    supported_formats: frozenset[ImageFormat]
    pipeline_schema: int

    @property
    def codec_fingerprint(self) -> str:
        """``name=version`` pairs joined by commas, ordered by name."""
        return ",".join(f"{name}={version}" for name, version in sorted(self.codec_versions))


def compute_variant_key(
    *,
    identity: SourceImageIdentity,
    width: int,
    image_format: ImageFormat,
    encoder: EncoderProfile,
    backend: BackendInfo,
) -> str:
    """Derive the cache key for one variant.

    The inputs are exactly what changes the produced bytes. Absolute checkout
    paths, build timestamps, temporary names, worker counts and the output
    directory are deliberately absent, which is what makes the same image,
    settings and backend produce the same bytes and the same published name on
    any machine.
    """
    fields = (
        str(CACHE_SCHEMA_VERSION),
        identity.source_relpath,
        identity.content_hash,
        str(width),
        image_format.value,
        encoder.profile_id,
        # Every encoder field -- profile_id included once more -- so a value
        # change can never reuse a variant encoded with the old settings.
        str(astuple(encoder)),
        backend.backend_id,
        backend.backend_version,
        backend.codec_fingerprint,
        str(backend.pipeline_schema),
        ORIENTATION_POLICY_ID,
        METADATA_POLICY_ID,
        ICC_POLICY_ID,
    )
    return hashlib.sha256("\x00".join(fields).encode("utf-8")).hexdigest()


def variant_cache_relpath(key: str, image_format: ImageFormat) -> PurePosixPath:
    """Cache location for *key*, sharded by its first two characters."""
    return PurePosixPath(key[:2]) / f"{key}{FORMAT_EXTENSIONS[image_format]}"


def variant_public_basename(*, identity: SourceImageIdentity, key: str, width: int, image_format: ImageFormat) -> str:
    """Published filename for one variant: readable stem, real width, key prefix.

    The stem is reduced to ASCII so the published URL needs no percent-encoding
    and behaves the same on every filesystem. Uniqueness comes from the key
    prefix, not the stem, so two different sources that reduce to the same stem
    still get distinct files.
    """
    stem = _safe_stem(identity.source_relpath)
    return f"{stem}-{width}w-{key[:_KEY_PREFIX_LENGTH]}{FORMAT_EXTENSIONS[image_format]}"


def _safe_stem(source_relpath: str) -> str:
    # Split the extension off the basename directly: ``Path.stem`` semantics for
    # dot-only names such as ``...jpg`` differ across Python versions, while the
    # contract needs the part before the last dot (here ``..``, which sanitises
    # to the ``image`` fallback).
    stem = PurePosixPath(source_relpath).name.rsplit(".", 1)[0]
    stem = _UNSAFE_STEM_CHARS.sub("-", stem)
    stem = _REPEATED_DASHES.sub("-", stem).strip("-.")
    return stem[:_MAX_STEM_LENGTH].strip("-.") or "image"


def select_candidate_widths(configured: Sequence[int], natural_width: int) -> tuple[int, ...]:
    """Widths to generate for an image whose natural width is *natural_width*.

    Configured widths at or above the natural width are dropped -- MaatLog never
    upscales -- and the natural width itself is always included, so even an
    image smaller than the smallest configured width still gets one candidate.
    """
    return tuple(sorted({width for width in configured if width < natural_width} | {natural_width}))


def scaled_height(*, natural_width: int, natural_height: int, target_width: int) -> int:
    """Height of the variant at *target_width*, preserving the aspect ratio.

    Rounded to the nearest integer (ties to even, as Python's ``round`` does) and
    floored at 1: a very wide, very short image must not scale to a zero-height
    file. One shared implementation keeps every candidate on the same ratio.
    """
    return max(1, round(natural_height * target_width / natural_width))


#: No usable image backend is installed.
IMAGE_BACKEND_MISSING: Final = "maatlog.image.backend-missing"

#: The backend cannot encode the requested output format.
IMAGE_CODEC_MISSING: Final = "maatlog.image.codec-missing"

#: The source bytes could not be decoded into an image.
IMAGE_DECODE_FAILED: Final = "maatlog.image.decode-failed"

#: The variant could not be encoded into the target format.
IMAGE_ENCODE_FAILED: Final = "maatlog.image.encode-failed"

#: The source image is too large to decode safely.
IMAGE_TOO_LARGE: Final = "maatlog.image.too-large"

#: The variant cache directory cannot be written to.
IMAGE_CACHE_UNWRITABLE: Final = "maatlog.image.cache-unwritable"


class ImageProcessingError(Exception):
    """A supported image could not be processed.

    Reserved for real failures: a corrupt JPEG, a missing codec, an unwritable
    cache. A format MaatLog simply does not resize -- SVG, GIF, an animation --
    is not a failure and never reaches this exception; the caller publishes the
    original instead.
    """

    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(format_diagnostic(diagnostic))


@dataclass(frozen=True, slots=True)
class SourceImageProbe:
    """What the backend reports about a source image before any resizing.

    ``width`` and ``height`` are the natural dimensions *after* EXIF orientation
    has been applied, so callers never see pre-rotation dimensions and never
    have to reason about them. Both are positive integers: a backend that
    cannot measure the image must fail instead of reporting zero.
    """

    image_format: ImageFormat
    width: int
    height: int
    is_multi_frame: bool
    has_alpha: bool


@dataclass(frozen=True, slots=True)
class VariantRequest:
    source_path: Path
    identity: SourceImageIdentity
    probe: SourceImageProbe
    width: int
    cache_root: Path


@dataclass(frozen=True, slots=True)
class GeneratedVariant:
    """One variant that exists on disk.

    ``width`` is the width of the file that was actually written, which is what
    a ``w`` descriptor must advertise -- not the width that was requested.
    """

    width: int
    height: int
    image_format: ImageFormat
    cache_path: Path
    public_basename: str
    byte_size: int


@runtime_checkable
class ImageVariantGenerator(Protocol):
    """Produces width variants of a source image.

    Implementations know nothing about Sphinx: they take a path and a width and
    return a file. Everything Sphinx-shaped -- registration, publication,
    incremental rebuilds -- lives on the caller's side of this boundary.
    """

    def describe_backend(self) -> BackendInfo:
        """Identify the backend precisely enough to key a cache on it.

        Raises :class:`ImageProcessingError` with
        :data:`IMAGE_BACKEND_MISSING` when no usable backend is installed.
        """
        ...

    def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        """Read dimensions and frame count without producing any output.

        Raises :class:`ImageProcessingError` on a decode failure
        (:data:`IMAGE_DECODE_FAILED`) or an image too large to decode safely
        (:data:`IMAGE_TOO_LARGE`).
        """
        ...

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        """Return the variant for *request*, reusing the cache when it is intact.

        Writes through a unique temporary file and an atomic replace, so a
        concurrent build never observes a partial file. Raises
        :class:`ImageProcessingError` on encode failure
        (:data:`IMAGE_ENCODE_FAILED`) or an unwritable cache
        (:data:`IMAGE_CACHE_UNWRITABLE`), and ``ValueError`` when
        ``request.width`` exceeds ``request.probe.width``, which
        :func:`select_candidate_widths` never produces.
        """
        ...


#: Directory under ``doctreedir`` that holds generated variants between builds.
RESPONSIVE_CACHE_DIRNAME: Final = "maatlog_responsive_images"

#: Directory under the builder's image directory that holds published variants.
#: Keeping MaatLog's files in their own subdirectory is what lets a build prove
#: which published files it owns, so stale-variant cleanup can never touch a
#: regular Sphinx image or another extension's output.
RESPONSIVE_OUTPUT_SUBDIR: Final = "maatlog"


@dataclass(frozen=True, slots=True)
class ResponsiveVariant:
    width: int
    height: int
    image_format: ImageFormat
    public_basename: str


@dataclass(frozen=True, slots=True)
class ResponsiveImageEntry:
    """Everything known about one source image's published variants.

    Deliberately free of ``Path`` objects and open files: this record is stored
    in the Sphinx environment, so it must pickle cleanly, and it is projected
    into templates, which have no business seeing filesystem paths.
    """

    identity: SourceImageIdentity
    natural_width: int
    natural_height: int
    image_format: ImageFormat
    variants: tuple[ResponsiveVariant, ...]


#: Published variants keyed by ``SourceImageIdentity.source_relpath``.
ResponsiveImageManifest: TypeAlias = Mapping[str, ResponsiveImageEntry]


@dataclass(frozen=True, slots=True)
class ResponsiveImageCandidate:
    url: str
    width: int


@dataclass(frozen=True, slots=True)
class ResponsiveImageView:
    """One responsive image as a theme draws it.

    Produced only for images MaatLog actually resized. A source it leaves alone
    -- SVG, GIF, an animation -- has no view at all, and the theme falls back to
    the single original URL it already renders. Presence of the view is the
    signal, which keeps templates from branching on empty candidate lists.
    """

    src: str
    candidates: tuple[ResponsiveImageCandidate, ...]
    width: int
    height: int
    usage: ImageUsage

    @property
    def srcset(self) -> str:
        return ", ".join(f"{candidate.url} {candidate.width}w" for candidate in self.candidates)


def build_responsive_image_view(
    entry: ResponsiveImageEntry, *, image_root_url: str, usage: ImageUsage
) -> ResponsiveImageView:
    """Project *entry* into page-relative URLs for one consumption site.

    *image_root_url* is the page-relative path to the published variant
    directory, as ``sphinx.util.osutil.relative_uri`` returns it. URL assembly
    lives here alone so a candidate URL and the ``src`` can never be built two
    different ways.
    """
    if not entry.variants:
        raise ValueError("a responsive image entry needs at least one variant")
    root = quote(image_root_url, safe="/:%")
    if root and not root.endswith("/"):
        root = f"{root}/"
    candidates = tuple(
        ResponsiveImageCandidate(url=f"{root}{variant.public_basename}", width=variant.width)
        for variant in sorted(entry.variants, key=lambda variant: variant.width)
    )
    return ResponsiveImageView(
        src=candidates[-1].url,
        candidates=candidates,
        width=entry.natural_width,
        height=entry.natural_height,
        usage=usage,
    )


VariantGeneratorFactory: TypeAlias = Callable[[], ImageVariantGenerator]

_FACTORY_ATTR: Final = "_maatlog_variant_generator_factory"
_GENERATOR_ATTR: Final = "_maatlog_variant_generator"


def responsive_images_enabled(config: MaatlogConfig, builder: Builder) -> bool:
    """Whether this build generates responsive image variants.

    Full HTML only. Other builders keep today's single-source behaviour and are
    never asked for an image backend.
    """
    return config.responsive_images and is_full_html_builder(builder)


def register_variant_generator_factory(app: Sphinx, factory: VariantGeneratorFactory) -> None:
    """Install the image backend for this application.

    The factory is called at most once per build, and only when responsive
    images are enabled, so registering one never costs a disabled build
    anything.
    """
    app.__dict__[_FACTORY_ATTR] = factory


def resolve_variant_generator(app: Sphinx) -> ImageVariantGenerator:
    """Return this build's generator, creating it on first use.

    Raises :class:`~maatlog.errors.MaatlogBuildError` when no backend is
    installed. Failing loudly is deliberate: silently dropping back to single
    ``src`` output would hide a broken installation behind pages that merely
    look slightly worse.
    """
    generator = app.__dict__.get(_GENERATOR_ATTR)
    if generator is not None:
        return cast(ImageVariantGenerator, generator)
    factory = app.__dict__.get(_FACTORY_ATTR)
    if factory is None:
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code=IMAGE_BACKEND_MISSING,
                    message="Responsive images are enabled but no image backend is available",
                    field="maatlog_responsive_images",
                    value="True",
                    expected='Pillow installed via: pip install "maatlog[images]"',
                )
            ]
        )
    created = cast(VariantGeneratorFactory, factory)()
    app.__dict__[_GENERATOR_ATTR] = created
    return created


def register_responsive_images(app: Sphinx) -> None:
    """Wire generator resolution into the Sphinx application."""
    app.connect("env-updated", _check_responsive_image_backend)


def _check_responsive_image_backend(app: Sphinx, env: object) -> None:
    """Resolve this build's generator on ``env-updated`` (default priority 500).

    This step no longer detects a missing backend, despite the name. ``setup()``
    always registers the bundled Pillow factory, and building the generator from
    it never imports Pillow, so ``resolve_variant_generator`` cannot fail here in
    a normal build -- only when something replaced the factory with none at all.
    What it still does is force the generator to exist before
    ``prepare_responsive_images`` (priority 600) needs it.

    A missing Pillow is reported by that later step, through
    ``describe_backend()``. It runs on ``env-updated`` too, so an enabled build
    without the ``images`` extra still fails before any page is written.
    """
    del env
    config = MaatlogConfig.from_sphinx(app.config)
    if not responsive_images_enabled(config, app.builder):
        return
    resolve_variant_generator(app)

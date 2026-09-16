"""Shared responsive-image test doubles for issues #215 and #216.

Frozen once issue #213 merges: #214, #215, #216 and #217 consume these and do
not change them. A change here moves the contract every parallel session builds
against, so it needs an Issue record and a plan revision, not a quiet edit.

Nothing here imports Pillow. That is the point: #215 can exercise the whole
enabled path, and #216 can render every template, without waiting for #214's
real generator or for an image backend to be installed.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from maatlog.image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    BackendInfo,
    GeneratedVariant,
    ImageFormat,
    ImageUsage,
    ResponsiveImageEntry,
    ResponsiveImageView,
    ResponsiveVariant,
    SourceImageIdentity,
    SourceImageProbe,
    VariantRequest,
    build_responsive_image_view,
    compute_variant_key,
    scaled_height,
    variant_cache_relpath,
    variant_public_basename,
)

JPEG_HEADER_BYTES: Final = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
WEBP_HEADER_BYTES: Final = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00"
GIF_BYTES: Final = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
SVG_BYTES: Final = b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="9"></svg>'

FAKE_BACKEND: Final = BackendInfo(
    backend_id="fake",
    backend_version="0",
    codec_versions=(("fake", "0"),),
    supported_formats=frozenset({ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP}),
    pipeline_schema=1,
)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def make_test_png(width: int, height: int, *, rgba: tuple[int, int, int, int] = (32, 64, 128, 255)) -> bytes:
    """Return a valid single-colour RGBA PNG, built without an image backend.

    Deterministic for the same arguments, so a test can assert on cache reuse
    and on stable published names.
    """
    header = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    row = b"\x00" + bytes(rgba) * width
    data = _png_chunk(b"IDAT", zlib.compress(row * height, 9))
    return b"\x89PNG\r\n\x1a\n" + header + data + _png_chunk(b"IEND", b"")


class FakeVariantGenerator:
    """An ``ImageVariantGenerator`` that writes deterministic placeholder bytes.

    Reports the geometry a real backend would report, so callers can assert on
    widths, heights, cache reuse and published names without decoding anything.
    """

    def __init__(self, probes: Mapping[str, SourceImageProbe], *, backend: BackendInfo | None = None) -> None:
        self._probes = dict(probes)
        self._backend = backend if backend is not None else FAKE_BACKEND
        self._calls: list[VariantRequest] = []
        self.encode_count = 0

    @property
    def generate_calls(self) -> tuple[VariantRequest, ...]:
        return tuple(self._calls)

    def describe_backend(self) -> BackendInfo:
        return self._backend

    def probe(self, source_path: Path, *, image_format: ImageFormat) -> SourceImageProbe:
        del image_format
        return self._probes[source_path.name]

    def generate(self, request: VariantRequest) -> GeneratedVariant:
        self._calls.append(request)
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
        if not cache_path.is_file():
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = hashlib.sha256(f"{key}:{request.width}".encode("ascii")).digest() * 4
            temporary = cache_path.with_name(f"{cache_path.name}.tmp")
            temporary.write_bytes(payload)
            temporary.replace(cache_path)
            self.encode_count += 1
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


def sample_responsive_image_entry(
    *,
    source_relpath: str = "posts/img/hero.png",
    natural_width: int = 1600,
    natural_height: int = 900,
    widths: tuple[int, ...] = (480, 768, 960, 1200, 1600),
) -> ResponsiveImageEntry:
    """A manifest entry shaped like a real one, for tests with no build behind them."""
    identity = SourceImageIdentity(source_relpath=source_relpath, content_hash="0" * 64)
    variants = tuple(
        ResponsiveVariant(
            width=width,
            height=scaled_height(natural_width=natural_width, natural_height=natural_height, target_width=width),
            image_format=ImageFormat.PNG,
            public_basename=variant_public_basename(
                identity=identity,
                key=compute_variant_key(
                    identity=identity,
                    width=width,
                    image_format=ImageFormat.PNG,
                    encoder=DEFAULT_ENCODER_PROFILE,
                    backend=FAKE_BACKEND,
                ),
                width=width,
                image_format=ImageFormat.PNG,
            ),
        )
        for width in widths
    )
    return ResponsiveImageEntry(
        identity=identity,
        natural_width=natural_width,
        natural_height=natural_height,
        image_format=ImageFormat.PNG,
        variants=variants,
    )


def sample_responsive_image_view(
    usage: ImageUsage = ImageUsage.POST_REPRESENTATIVE,
    *,
    image_root_url: str = "_images/maatlog/",
    entry: ResponsiveImageEntry | None = None,
) -> ResponsiveImageView:
    """A theme-ready view, for template tests that run before #215 lands."""
    return build_responsive_image_view(
        entry if entry is not None else sample_responsive_image_entry(),
        image_root_url=image_root_url,
        usage=usage,
    )

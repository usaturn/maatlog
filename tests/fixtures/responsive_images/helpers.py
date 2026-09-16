"""Shared responsive-image request helper for generator tests (issue #214)."""

from __future__ import annotations

from pathlib import Path

from maatlog.image_contracts import VariantRequest, build_source_identity, sniff_source_format
from maatlog.responsive_images import PillowImageVariantGenerator


def make_request(path: Path, *, srcdir: Path, cache_root: Path, width: int) -> VariantRequest:
    """Build a :class:`VariantRequest` for an already-generated image file."""
    fmt = sniff_source_format(path)
    assert fmt is not None
    return VariantRequest(
        source_path=path,
        identity=build_source_identity(path, srcdir=srcdir),
        probe=PillowImageVariantGenerator().probe(path, image_format=fmt),
        width=width,
        cache_root=cache_root,
    )

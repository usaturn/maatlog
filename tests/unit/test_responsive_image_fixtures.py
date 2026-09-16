from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.responsive_image_fixtures import (
    GIF_BYTES,
    JPEG_HEADER_BYTES,
    SVG_BYTES,
    WEBP_HEADER_BYTES,
    FakeVariantGenerator,
    make_test_png,
    sample_responsive_image_entry,
    sample_responsive_image_view,
)

from maatlog.image_contracts import (
    ImageFormat,
    ImageUsage,
    ImageVariantGenerator,
    SourceImageIdentity,
    SourceImageProbe,
    VariantRequest,
    scaled_height,
    sniff_image_format,
)


def test_make_test_png_is_a_real_png() -> None:
    data = make_test_png(4, 3)
    assert sniff_image_format(data) is ImageFormat.PNG
    assert make_test_png(4, 3) == data


def test_sample_bytes_sniff_as_expected() -> None:
    assert sniff_image_format(JPEG_HEADER_BYTES) is ImageFormat.JPEG
    assert sniff_image_format(WEBP_HEADER_BYTES) is ImageFormat.WEBP
    assert sniff_image_format(GIF_BYTES) is None
    assert sniff_image_format(SVG_BYTES) is None


def test_fake_generator_satisfies_the_protocol() -> None:
    generator = FakeVariantGenerator(probes={})
    assert isinstance(generator, ImageVariantGenerator)


def test_fake_generator_produces_files_and_records_calls(tmp_path: Path) -> None:
    source = tmp_path / "hero.png"
    source.write_bytes(make_test_png(1600, 900))
    identity = SourceImageIdentity(source_relpath="hero.png", content_hash="a" * 64)
    probe = SourceImageProbe(
        image_format=ImageFormat.PNG, width=1600, height=900, is_multi_frame=False, has_alpha=False
    )
    generator = FakeVariantGenerator(probes={"hero.png": probe})
    assert generator.probe(source, image_format=ImageFormat.PNG) == probe

    request = VariantRequest(
        source_path=source, identity=identity, probe=probe, width=480, cache_root=tmp_path / "cache"
    )
    variant = generator.generate(request)
    assert variant.width == 480
    assert variant.height == scaled_height(natural_width=1600, natural_height=900, target_width=480)
    assert variant.cache_path.is_file()
    assert variant.byte_size == variant.cache_path.stat().st_size
    assert generator.generate_calls == (request,)


def test_fake_generator_reuses_the_cache(tmp_path: Path) -> None:
    source = tmp_path / "hero.png"
    source.write_bytes(make_test_png(1600, 900))
    probe = SourceImageProbe(
        image_format=ImageFormat.PNG, width=1600, height=900, is_multi_frame=False, has_alpha=False
    )
    generator = FakeVariantGenerator(probes={"hero.png": probe})
    request = VariantRequest(
        source_path=source,
        identity=SourceImageIdentity(source_relpath="hero.png", content_hash="a" * 64),
        probe=probe,
        width=480,
        cache_root=tmp_path / "cache",
    )
    first = generator.generate(request)
    second = generator.generate(request)
    assert first == second
    assert generator.encode_count == 1


def test_fake_generator_rejects_upscaling(tmp_path: Path) -> None:
    source = tmp_path / "hero.png"
    source.write_bytes(make_test_png(100, 50))
    probe = SourceImageProbe(image_format=ImageFormat.PNG, width=100, height=50, is_multi_frame=False, has_alpha=False)
    generator = FakeVariantGenerator(probes={"hero.png": probe})
    request = VariantRequest(
        source_path=source,
        identity=SourceImageIdentity(source_relpath="hero.png", content_hash="a" * 64),
        probe=probe,
        width=480,
        cache_root=tmp_path / "cache",
    )
    with pytest.raises(ValueError, match="upscale"):
        generator.generate(request)


def test_sample_view_defaults_are_usable_by_theme_tests() -> None:
    view = sample_responsive_image_view()
    assert view.usage is ImageUsage.POST_REPRESENTATIVE
    assert view.candidates
    assert view.src == view.candidates[-1].url
    assert view.srcset.count("w") >= len(view.candidates)
    assert sample_responsive_image_view(usage=ImageUsage.POST_TOP).usage is ImageUsage.POST_TOP


def test_sample_entry_matches_the_sample_view() -> None:
    entry = sample_responsive_image_entry()
    view = sample_responsive_image_view()
    assert entry.natural_width == view.width
    assert entry.natural_height == view.height
    assert len(entry.variants) == len(view.candidates)

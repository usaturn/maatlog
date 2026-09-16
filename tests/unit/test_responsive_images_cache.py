"""Verified cache reuse and atomic publication tests (issue #214, task 5).

Every test builds its sources with Pillow in ``tmp_path`` only; no external
downloads. Every successful ``generate`` in this file goes through
``_generate_checked``, which asserts the ``ImageVariantGenerator`` protocol and
re-validates the returned paths, dimensions and byte size against the
filesystem and the request.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fixtures.responsive_images.helpers import make_request
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from PIL import Image

from maatlog._responsive_image_cache import get_or_create
from maatlog.image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    IMAGE_CACHE_UNWRITABLE,
    IMAGE_CODEC_MISSING,
    IMAGE_DECODE_FAILED,
    IMAGE_ENCODE_FAILED,
    IMAGE_TOO_LARGE,
    BackendInfo,
    GeneratedVariant,
    ImageFormat,
    ImageProcessingError,
    ImageVariantGenerator,
    SourceImageIdentity,
    SourceImageProbe,
    VariantRequest,
    compute_variant_key,
    scaled_height,
    variant_cache_relpath,
    variant_public_basename,
)
from maatlog.responsive_images import PillowImageVariantGenerator

_NATURAL_SIZE = (17, 9)
_WIDTH = 7


def _save_png(path: Path, size: tuple[int, int] = _NATURAL_SIZE, color: Any = (10, 40, 90, 120)) -> None:
    Image.new("RGBA", size, color).save(path, format="PNG")


def _request(path: Path, tmp_path: Path, width: int = _WIDTH) -> VariantRequest:
    return make_request(path, srcdir=tmp_path, cache_root=tmp_path / "cache", width=width)


def _expected_key(generator: PillowImageVariantGenerator, request: VariantRequest) -> str:
    return compute_variant_key(
        identity=request.identity,
        width=request.width,
        image_format=request.probe.image_format,
        encoder=generator.encoder,
        backend=generator.describe_backend(),
    )


def _generate_checked(generator: PillowImageVariantGenerator, request: VariantRequest) -> GeneratedVariant:
    """Generate and re-validate the result against the filesystem and request."""
    assert isinstance(generator, ImageVariantGenerator)
    result = generator.generate(request)
    key = _expected_key(generator, request)
    expected_height = scaled_height(
        natural_width=request.probe.width,
        natural_height=request.probe.height,
        target_width=request.width,
    )
    assert result.cache_path == request.cache_root / variant_cache_relpath(key, request.probe.image_format)
    assert result.cache_path.is_file()
    assert result.width == request.width
    assert result.height == expected_height
    assert result.image_format is request.probe.image_format
    assert result.public_basename == variant_public_basename(
        identity=request.identity, key=key, width=request.width, image_format=request.probe.image_format
    )
    assert result.byte_size == result.cache_path.stat().st_size
    assert result.byte_size > 0
    with Image.open(result.cache_path) as image:
        image.load()
        assert image.size == (result.width, result.height)
    return result


def _save_spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count Pillow saves (one per encoded variant) without changing behaviour."""
    original_save = Image.Image.save
    calls: list[int] = []

    def counted_save(self: Image.Image, fp: Any, format: str | None = None, **params: Any) -> None:
        calls.append(1)
        original_save(self, fp, format=format, **params)

    monkeypatch.setattr(Image.Image, "save", counted_save)
    return calls


def _sidecar_of(target: Path) -> Path:
    return target.with_name(target.name + ".json")


# ---------------------------------------------------------------------------
# Core reuse contract (brief step 1, verbatim)
# ---------------------------------------------------------------------------


def test_cache_reuse_and_corruption_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    Image.new("RGBA", (17, 9), (10, 40, 90, 120)).save(src)
    request = make_request(src, srcdir=tmp_path, cache_root=tmp_path / "cache", width=7)
    generator = PillowImageVariantGenerator()
    first = generator.generate(request)
    expected = first.cache_path.read_bytes()
    original_save = Image.Image.save
    calls: list[int] = []

    def counted_save(self: Image.Image, *args: Any, **kwargs: Any) -> None:
        calls.append(1)
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", counted_save)
    assert generator.generate(request) == first
    assert calls == []
    first.cache_path.write_bytes(b"broken cache")
    restored = generator.generate(request)
    assert restored.cache_path.read_bytes() == expected
    assert len(calls) == 1
    assert restored.byte_size == restored.cache_path.stat().st_size


def test_generate_returns_verified_result(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    _generate_checked(PillowImageVariantGenerator(), _request(src, tmp_path))


def test_cache_path_shards_by_key_prefix(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    result = _generate_checked(generator, _request(src, tmp_path))
    key = _expected_key(generator, _request(src, tmp_path))
    assert result.cache_path.parent.name == key[:2]
    assert result.cache_path.name.startswith(key)
    assert result.cache_path.suffix == ".png"


# ---------------------------------------------------------------------------
# Request validation: ValueError before any cache write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", [True, False, 0, -1, 18, "7", 7.0, None, (7,)])
def test_invalid_width_rejected_without_cache(tmp_path: Path, width: Any) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = replace(_request(src, tmp_path), width=width)
    with pytest.raises(ValueError, match="width"):
        PillowImageVariantGenerator().generate(request)
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("dims", [(0, 9), (17, 0), (-17, 9), (17, -9)])
def test_invalid_probe_dimensions_rejected_without_cache(tmp_path: Path, dims: tuple[int, int]) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)
    bad_probe = replace(request.probe, width=dims[0], height=dims[1])
    with pytest.raises(ValueError, match="[Dd]imension|probe|width|height"):
        PillowImageVariantGenerator().generate(replace(request, probe=bad_probe))
    assert not (tmp_path / "cache").exists()


def test_multiframe_generate_rejected_without_cache(tmp_path: Path) -> None:
    src = tmp_path / "animated.webp"
    first = Image.new("RGB", (8, 5), (200, 30, 30))
    second = Image.new("RGB", (8, 5), (30, 30, 200))
    first.save(src, format="WEBP", save_all=True, append_images=[second], duration=100, loop=0)
    request = make_request(src, srcdir=tmp_path, cache_root=tmp_path / "cache", width=8)
    assert request.probe.is_multi_frame
    with pytest.raises(ValueError, match="[Mm]ulti-frame|animation"):
        PillowImageVariantGenerator().generate(request)
    assert not (tmp_path / "cache").exists()


# ---------------------------------------------------------------------------
# Encoder profile validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resample", "bicubic"),
        ("resample", ""),
        ("resample", 123),
        ("jpeg_quality", -1),
        ("jpeg_quality", 101),
        ("jpeg_quality", True),
        ("jpeg_quality", "82"),
        ("jpeg_subsampling", -1),
        ("jpeg_subsampling", 3),
        ("jpeg_subsampling", True),
        ("png_compress_level", -1),
        ("png_compress_level", 10),
        ("png_compress_level", False),
        ("webp_quality", -1),
        ("webp_quality", 101),
        ("webp_quality", True),
        ("webp_alpha_quality", -1),
        ("webp_alpha_quality", 101),
        ("webp_method", -1),
        ("webp_method", 7),
        ("webp_method", False),
        ("jpeg_progressive", 1),
        ("jpeg_progressive", "yes"),
        ("jpeg_progressive", None),
        ("jpeg_optimize", 0),
        ("png_optimize", "true"),
        ("png_optimize", 1),
        ("webp_exact", 1),
        ("webp_exact", 0),
        ("profile_id", ""),
        ("profile_id", None),
        ("profile_id", 123),
    ],
)
def test_invalid_encoder_rejected_without_cache(tmp_path: Path, field: str, value: Any) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    bad_encoder = replace(DEFAULT_ENCODER_PROFILE, **{field: value})
    with pytest.raises(ValueError, match=field):
        PillowImageVariantGenerator(encoder=bad_encoder).generate(_request(src, tmp_path))
    assert not (tmp_path / "cache").exists()


def test_encoder_boundaries_generate_successfully(tmp_path: Path) -> None:
    png_src = tmp_path / "flat.png"
    Image.new("RGB", (16, 10), (200, 30, 30)).save(png_src, format="PNG")
    _generate_checked(
        PillowImageVariantGenerator(
            encoder=replace(DEFAULT_ENCODER_PROFILE, png_compress_level=0, png_optimize=False)
        ),
        _request(png_src, tmp_path, width=8),
    )
    jpg_src = tmp_path / "photo.jpg"
    Image.new("RGB", (16, 10), (200, 30, 30)).save(jpg_src, format="JPEG")
    _generate_checked(
        PillowImageVariantGenerator(
            encoder=replace(
                DEFAULT_ENCODER_PROFILE,
                jpeg_quality=0,
                jpeg_progressive=False,
                jpeg_optimize=False,
                jpeg_subsampling=0,
            )
        ),
        _request(jpg_src, tmp_path, width=8),
    )
    _generate_checked(
        PillowImageVariantGenerator(encoder=replace(DEFAULT_ENCODER_PROFILE, jpeg_quality=100, jpeg_subsampling=2)),
        _request(jpg_src, tmp_path, width=16),
    )
    webp_src = tmp_path / "alpha.webp"
    Image.new("RGBA", (16, 10), (200, 30, 30, 128)).save(webp_src, format="WEBP")
    _generate_checked(
        PillowImageVariantGenerator(
            encoder=replace(
                DEFAULT_ENCODER_PROFILE,
                webp_quality=0,
                webp_method=0,
                webp_alpha_quality=0,
                webp_exact=False,
            )
        ),
        _request(webp_src, tmp_path, width=8),
    )
    _generate_checked(
        PillowImageVariantGenerator(
            encoder=replace(DEFAULT_ENCODER_PROFILE, webp_quality=100, webp_method=6, webp_alpha_quality=100)
        ),
        _request(webp_src, tmp_path, width=16),
    )


# ---------------------------------------------------------------------------
# Cache key contract
# ---------------------------------------------------------------------------


def test_same_filename_different_dirs_have_distinct_variants(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _save_png(dir_a / "hero.png")
    _save_png(dir_b / "hero.png")
    generator = PillowImageVariantGenerator()
    request_a = make_request(dir_a / "hero.png", srcdir=tmp_path, cache_root=tmp_path / "cache", width=7)
    request_b = make_request(dir_b / "hero.png", srcdir=tmp_path, cache_root=tmp_path / "cache", width=7)
    assert request_a.identity.source_relpath == "a/hero.png"
    assert request_b.identity.source_relpath == "b/hero.png"
    first = _generate_checked(generator, request_a)
    second = _generate_checked(generator, request_b)
    assert first.cache_path != second.cache_path


def test_identical_bytes_different_roots_share_key_shape(tmp_path: Path) -> None:
    for root_name in ("root-a", "root-b"):
        root = tmp_path / root_name
        (root / "sub").mkdir(parents=True)
        _save_png(root / "sub" / "hero.png")
    request_a = make_request(
        tmp_path / "root-a" / "sub" / "hero.png",
        srcdir=tmp_path / "root-a",
        cache_root=tmp_path / "cache-a",
        width=7,
    )
    request_b = make_request(
        tmp_path / "root-b" / "sub" / "hero.png",
        srcdir=tmp_path / "root-b",
        cache_root=tmp_path / "cache-b",
        width=7,
    )
    assert request_a.identity.source_relpath == request_b.identity.source_relpath == "sub/hero.png"
    assert request_a.identity.content_hash == request_b.identity.content_hash
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, request_a)
    second = _generate_checked(generator, request_b)
    assert first.cache_path.parent.name == second.cache_path.parent.name
    assert first.cache_path.name == second.cache_path.name
    assert first.public_basename == second.public_basename
    assert first.cache_path.read_bytes() == second.cache_path.read_bytes()


def test_changed_source_bytes_change_key(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    _save_png(src, color=(200, 30, 30, 255))
    second = _generate_checked(generator, _request(src, tmp_path))
    assert first.cache_path != second.cache_path


@pytest.mark.parametrize(
    "field",
    [
        "profile_id",
        "jpeg_quality",
        "jpeg_progressive",
        "jpeg_optimize",
        "jpeg_subsampling",
        "png_optimize",
        "png_compress_level",
        "webp_quality",
        "webp_method",
        "webp_alpha_quality",
        "webp_exact",
    ],
)
def test_each_encoder_field_changes_key(tmp_path: Path, field: str) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    first = _generate_checked(generator, request)
    current = getattr(DEFAULT_ENCODER_PROFILE, field)
    if isinstance(current, bool):
        changed = not current
    elif isinstance(current, int):
        changed = current - 1 if current > 0 else current + 1
    else:
        changed = f"{current}-changed"
    tuned = PillowImageVariantGenerator(encoder=replace(DEFAULT_ENCODER_PROFILE, **{field: changed}))
    expected = compute_variant_key(
        identity=request.identity,
        width=request.width,
        image_format=request.probe.image_format,
        encoder=tuned.encoder,
        backend=tuned.describe_backend(),
    )
    assert expected != _expected_key(generator, request)
    second = _generate_checked(tuned, request)
    assert second.cache_path != first.cache_path
    assert second.cache_path.name.startswith(expected)


def test_backend_fingerprint_change_changes_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    first = _generate_checked(generator, request)
    backend = generator.describe_backend()

    def patched_backend(self: PillowImageVariantGenerator) -> BackendInfo:
        return replace(backend, backend_version="0-test")

    monkeypatch.setattr(PillowImageVariantGenerator, "describe_backend", patched_backend)
    second = generator.generate(request)
    assert second.cache_path != first.cache_path
    assert second.cache_path.name.startswith(
        compute_variant_key(
            identity=request.identity,
            width=request.width,
            image_format=request.probe.image_format,
            encoder=generator.encoder,
            backend=replace(backend, backend_version="0-test"),
        )
    )


def test_pipeline_schema_change_changes_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    first = _generate_checked(generator, request)
    monkeypatch.setattr("maatlog.responsive_images.PIPELINE_SCHEMA", 2)
    second = generator.generate(request)
    assert second.cache_path != first.cache_path


# ---------------------------------------------------------------------------
# Stale identity / probe facts: decode-failed, never a successful return
# ---------------------------------------------------------------------------


def test_stale_content_hash_rejected(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)
    generator = PillowImageVariantGenerator()
    _save_png(src, color=(200, 30, 30, 255))
    with pytest.raises(ImageProcessingError) as caught:
        generator.generate(request)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED
    target = request.cache_root / variant_cache_relpath(_expected_key(generator, request), request.probe.image_format)
    assert not target.exists()


def test_tampered_identity_hash_rejected(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)
    tampered = replace(request, identity=replace(request.identity, content_hash="0" * 64))
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(tampered)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


@pytest.mark.parametrize("fact", ["width", "height", "image_format", "has_alpha"])
def test_changed_probe_facts_rejected(tmp_path: Path, fact: str) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)
    if fact == "width":
        probe = replace(request.probe, width=request.probe.width + 1)
    elif fact == "height":
        probe = replace(request.probe, height=request.probe.height + 1)
    elif fact == "image_format":
        probe = replace(request.probe, image_format=ImageFormat.JPEG)
    else:
        probe = replace(request.probe, has_alpha=not request.probe.has_alpha)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(replace(request, probe=probe))
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


# ---------------------------------------------------------------------------
# Corruption recovery: any damage means regenerate
# ---------------------------------------------------------------------------


def test_truncated_cache_regenerates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    calls = _save_spy(monkeypatch)
    first.cache_path.write_bytes(expected[: len(expected) // 2])
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected
    assert calls == [1]


def test_pixel_swapped_cache_regenerates(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    Image.new("RGBA", (7, 4), (200, 30, 30, 255)).save(first.cache_path, format="PNG")
    assert first.cache_path.read_bytes() != expected
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected


def test_wrong_format_bytes_regenerate(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    buffer = BytesIO()
    Image.new("RGB", (7, 4), (200, 30, 30)).save(buffer, format="JPEG")
    first.cache_path.write_bytes(buffer.getvalue())
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected


def test_wrong_size_bytes_regenerate(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    Image.new("RGBA", (3, 3), (200, 30, 30, 255)).save(first.cache_path, format="PNG")
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected


def test_metadata_bearing_output_regenerates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL.PngImagePlugin import PngInfo

    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    info = PngInfo()
    info.add_text("Title", "secret-title")
    dirty = BytesIO()
    Image.new("RGBA", (7, 4), (200, 30, 30, 255)).save(dirty, format="PNG", pnginfo=info)
    dirty_bytes = dirty.getvalue()
    first.cache_path.write_bytes(dirty_bytes)
    sidecar = _sidecar_of(first.cache_path)
    record = json.loads(sidecar.read_bytes())
    record["sha256"] = hashlib.sha256(dirty_bytes).hexdigest()
    record["byte_size"] = len(dirty_bytes)
    sidecar.write_bytes((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    calls = _save_spy(monkeypatch)
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected
    assert calls == [1]


def test_missing_sidecar_regenerates(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    _sidecar_of(first.cache_path).unlink()
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected


@pytest.mark.parametrize(
    "mutation",
    [
        "bad-json",
        "empty",
        "truncated",
        "list-record",
        "schema",
        "key",
        "sha256",
        "byte_size",
        "width",
        "height",
        "image_format",
        "missing-key",
        "missing-sha256",
    ],
)
def test_corrupt_sidecar_regenerates(tmp_path: Path, mutation: str) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    expected = first.cache_path.read_bytes()
    sidecar = _sidecar_of(first.cache_path)
    valid = sidecar.read_bytes()
    if mutation == "bad-json":
        sidecar.write_bytes(b"{not json")
    elif mutation == "empty":
        sidecar.write_bytes(b"")
    elif mutation == "truncated":
        sidecar.write_bytes(valid[:10])
    elif mutation == "list-record":
        sidecar.write_bytes(b"[1, 2, 3]\n")
    else:
        record: Any = json.loads(valid)
        if mutation == "schema":
            record["schema"] = 2
        elif mutation == "key":
            record["key"] = "0" * 64
        elif mutation == "sha256":
            record["sha256"] = "0" * 64
        elif mutation == "byte_size":
            record["byte_size"] = record["byte_size"] + 1
        elif mutation == "width":
            record["width"] = record["width"] + 1
        elif mutation == "height":
            record["height"] = record["height"] + 1
        elif mutation == "image_format":
            record["image_format"] = ImageFormat.JPEG.value
        elif mutation == "missing-key":
            del record["key"]
        elif mutation == "missing-sha256":
            del record["sha256"]
        else:  # pragma: no cover - parametrize list above is exhaustive
            raise AssertionError(f"unknown sidecar mutation {mutation}")
        sidecar.write_bytes((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    restored = _generate_checked(generator, _request(src, tmp_path))
    assert restored.cache_path.read_bytes() == expected


def test_sidecar_record_shape_is_canonical(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    result = _generate_checked(generator, request)
    raw = _sidecar_of(result.cache_path).read_bytes()
    assert raw.endswith(b"\n")
    record = json.loads(raw)
    image_bytes = result.cache_path.read_bytes()
    assert record == {
        "schema": 1,
        "key": _expected_key(generator, request),
        "sha256": hashlib.sha256(image_bytes).hexdigest(),
        "byte_size": len(image_bytes),
        "width": request.width,
        "height": scaled_height(
            natural_width=request.probe.width,
            natural_height=request.probe.height,
            target_width=request.width,
        ),
        "image_format": request.probe.image_format.value,
    }
    assert raw == (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def test_unwritable_cache_mkdir_maps_to_cache_unwritable(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"not a directory")
    request = make_request(src, srcdir=tmp_path, cache_root=blocker / "cache", width=7)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CACHE_UNWRITABLE


def test_unwritable_cache_mkstemp_maps_to_cache_unwritable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tempfile, "mkstemp", _boom)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CACHE_UNWRITABLE


def test_unwritable_cache_sidecar_write_maps_to_cache_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "fdopen", _boom)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CACHE_UNWRITABLE


def test_unwritable_cache_fsync_maps_to_cache_unwritable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CACHE_UNWRITABLE


def test_unwritable_cache_replace_maps_to_cache_unwritable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CACHE_UNWRITABLE
    assert [item for item in (tmp_path / "cache").rglob("*") if item.is_file()] == []


def test_encoder_save_oserror_maps_to_encode_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)
    original_save = Image.Image.save

    def failing_save(self: Image.Image, fp: Any, format: str | None = None, **params: Any) -> None:
        raise OSError("simulated encoder failure")

    generator = PillowImageVariantGenerator()
    monkeypatch.setattr(Image.Image, "save", failing_save)
    with pytest.raises(ImageProcessingError) as caught:
        generator.generate(request)
    assert caught.value.diagnostic.code == IMAGE_ENCODE_FAILED
    target = request.cache_root / variant_cache_relpath(_expected_key(generator, request), request.probe.image_format)
    assert not target.exists()
    assert [item for item in (tmp_path / "cache").rglob("*") if item.is_file()] == []
    monkeypatch.setattr(Image.Image, "save", original_save)
    _generate_checked(PillowImageVariantGenerator(), request)


def test_encoder_save_value_error_maps_to_encode_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)

    def failing_save(self: Image.Image, fp: Any, format: str | None = None, **params: Any) -> None:
        raise ValueError("simulated format failure")

    monkeypatch.setattr(Image.Image, "save", failing_save)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(_request(src, tmp_path))
    assert caught.value.diagnostic.code == IMAGE_ENCODE_FAILED


def test_truncated_source_snapshot_rejected(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src, size=(64, 64))
    truncated = src.read_bytes()[: len(src.read_bytes()) // 2]
    assert len(truncated) > 32
    src.write_bytes(truncated)
    request = VariantRequest(
        source_path=src,
        identity=SourceImageIdentity(source_relpath="hero.png", content_hash=hashlib.sha256(truncated).hexdigest()),
        probe=SourceImageProbe(
            image_format=ImageFormat.PNG, width=64, height=64, is_multi_frame=False, has_alpha=False
        ),
        width=32,
        cache_root=tmp_path / "cache",
    )
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_snapshot_reprobe_failure_attaches_source(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src, size=(64, 64))
    truncated = src.read_bytes()[: len(src.read_bytes()) // 2]
    src.write_bytes(truncated)
    request = VariantRequest(
        source_path=src,
        identity=SourceImageIdentity(source_relpath="hero.png", content_hash=hashlib.sha256(truncated).hexdigest()),
        probe=SourceImageProbe(
            image_format=ImageFormat.PNG, width=64, height=64, is_multi_frame=False, has_alpha=False
        ),
        width=32,
        cache_root=tmp_path / "cache",
    )
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED
    assert caught.value.diagnostic.source == str(src)


def test_palette_cms_transform_failure_maps_to_decode_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import ImageCms

    src = tmp_path / "palette.png"
    paletted = Image.new("P", (8, 8))
    paletted.putpalette([200, 30, 30, 30, 200, 30, 30, 30, 200] * 85 + [0])
    paletted.save(src, format="PNG")
    request = make_request(src, srcdir=tmp_path, cache_root=tmp_path / "cache", width=8)

    def failing_transform(*args: Any, **kwargs: Any) -> Any:
        raise ImageCms.PyCMSError("simulated transform failure")

    monkeypatch.setattr(ImageCms, "profileToProfile", failing_transform)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_corrupt_palette_icc_rejected_without_raw_oserror(tmp_path: Path) -> None:
    src = tmp_path / "palette.png"
    paletted = Image.new("P", (8, 8))
    paletted.putpalette([255, 0, 0] * 256)
    buffer = BytesIO()
    paletted.save(buffer, format="PNG", icc_profile=b"not-an-icc")
    src.write_bytes(buffer.getvalue())
    request = make_request(src, srcdir=tmp_path, cache_root=tmp_path / "cache", width=8)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_palette_without_littlecms2_maps_to_codec_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import ImageCms
    from PIL._util import DeferredError

    src = tmp_path / "palette.png"
    paletted = Image.new("P", (8, 8))
    paletted.putpalette([255, 0, 0] * 256)
    paletted.save(src, format="PNG")
    request = make_request(src, srcdir=tmp_path, cache_root=tmp_path / "cache", width=8)
    monkeypatch.setattr(ImageCms, "core", DeferredError.new(ImportError("The _imagingcms C module is not installed")))
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CODEC_MISSING


# ---------------------------------------------------------------------------
# Hit-path behaviour
# ---------------------------------------------------------------------------


def test_warm_hit_verifies_source_hash(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    _generate_checked(generator, request)
    _save_png(src, color=(200, 30, 30, 255))
    with pytest.raises(ImageProcessingError) as caught:
        generator.generate(request)
    assert caught.value.diagnostic.code == IMAGE_DECODE_FAILED


def test_warm_hit_over_lowered_pixel_limit_reports_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    _generate_checked(generator, request)
    # The cached 7x4 variant (28 px) exceeds 2 * 10; the source does too.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ImageProcessingError) as caught:
        generator.generate(request)
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE
    assert caught.value.diagnostic.source == str(src)


def test_warm_hit_warning_band_maps_to_too_large_without_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    request = _request(src, tmp_path)
    _generate_checked(generator, request)
    # 20 < 28 <= 40: the cached variant lands in Pillow's warning band.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 20)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with pytest.raises(ImageProcessingError) as caught:
            generator.generate(request)
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE
    assert not any(issubclass(warning.category, Image.DecompressionBombWarning) for warning in recorded)


def test_source_warning_band_maps_to_too_large_without_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)
    # 100 < 153 <= 200: the source lands in Pillow's warning band on a miss.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with pytest.raises(ImageProcessingError) as caught:
            PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_TOO_LARGE
    assert caught.value.diagnostic.source == str(src)
    assert not any(issubclass(warning.category, Image.DecompressionBombWarning) for warning in recorded)


def test_changed_cache_root_regenerates_identical_bytes(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    generator = PillowImageVariantGenerator()
    first = _generate_checked(generator, _request(src, tmp_path))
    relocated = replace(_request(src, tmp_path), cache_root=tmp_path / "cache-b")
    second = _generate_checked(generator, relocated)
    assert second.cache_path != first.cache_path
    assert second.public_basename == first.public_basename
    assert second.cache_path.read_bytes() == first.cache_path.read_bytes()
    assert second.byte_size == first.byte_size


def test_failed_write_leaves_no_partials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hero.png"
    _save_png(src)
    request = _request(src, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> tuple[int, str]:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tempfile, "mkstemp", _boom)
    with pytest.raises(ImageProcessingError) as caught:
        PillowImageVariantGenerator().generate(request)
    assert caught.value.diagnostic.code == IMAGE_CACHE_UNWRITABLE
    assert [item for item in (tmp_path / "cache").rglob("*") if item.is_file()] == []
    monkeypatch.undo()
    _generate_checked(PillowImageVariantGenerator(), request)


# ---------------------------------------------------------------------------
# get_or_create unit contract: path/hash/json/temp/replace only
# ---------------------------------------------------------------------------


def _memory_callbacks(
    payload: bytes, dims: tuple[int, int]
) -> tuple[list[Path], Callable[[Path], None], Callable[[Path], tuple[int, int]]]:
    calls: list[Path] = []

    def write(path: Path) -> None:
        calls.append(path)
        path.write_bytes(payload)

    def inspect(path: Path) -> tuple[int, int]:
        assert path.is_file()
        return dims

    return calls, write, inspect


def test_get_or_create_hit_skips_write(tmp_path: Path) -> None:
    target = tmp_path / "cache" / "ab" / "abcdef.png"
    payload = b"\x89PNG" + b"\x00" * 16
    calls, write, inspect = _memory_callbacks(payload, (4, 2))
    first = get_or_create(
        target=target, key="k" * 64, width=4, height=2, image_format=ImageFormat.PNG, write=write, inspect=inspect
    )
    assert first == len(payload)
    assert len(calls) == 1
    assert calls[0] != target
    assert calls[0].parent == target.parent
    assert calls[0].name.startswith("." + target.name + ".")
    assert calls[0].name.endswith(".tmp")
    assert target.read_bytes() == payload
    second = get_or_create(
        target=target, key="k" * 64, width=4, height=2, image_format=ImageFormat.PNG, write=write, inspect=inspect
    )
    assert second == first
    assert len(calls) == 1


def test_get_or_create_recovers_from_garbage(tmp_path: Path) -> None:
    target = tmp_path / "cache" / "abcdef.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"garbage")
    _sidecar_of(target).write_bytes(b"garbage")
    payload = b"fresh-bytes"
    calls, write, inspect = _memory_callbacks(payload, (4, 2))
    assert get_or_create(
        target=target,
        key="k" * 64,
        width=4,
        height=2,
        image_format=ImageFormat.PNG,
        write=write,
        inspect=inspect,
    ) == len(payload)
    assert len(calls) == 1
    assert target.read_bytes() == payload


def test_get_or_create_final_verification_failure_raises(tmp_path: Path) -> None:
    target = tmp_path / "cache" / "abcdef.png"
    dims = iter([(4, 2), (999, 999)])

    def write(path: Path) -> None:
        path.write_bytes(b"payload")

    def inspect(path: Path) -> tuple[int, int]:
        return next(dims)

    with pytest.raises(ValueError, match="[Vv]erification|dimension"):
        get_or_create(
            target=target,
            key="k" * 64,
            width=4,
            height=2,
            image_format=ImageFormat.PNG,
            write=write,
            inspect=inspect,
        )


def test_get_or_create_write_failure_cleans_own_temps(tmp_path: Path) -> None:
    target = tmp_path / "cache" / "abcdef.png"

    def write(path: Path) -> None:
        path.write_bytes(b"partial")
        raise RuntimeError("boom")

    def inspect(path: Path) -> tuple[int, int]:
        return (4, 2)  # pragma: no cover - write always fails first

    with pytest.raises(RuntimeError, match="boom"):
        get_or_create(
            target=target,
            key="k" * 64,
            width=4,
            height=2,
            image_format=ImageFormat.PNG,
            write=write,
            inspect=inspect,
        )
    assert list((tmp_path / "cache").rglob("*")) == []

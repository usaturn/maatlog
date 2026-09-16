"""Backend discovery tests for the lazy Pillow responsive-image backend."""

from __future__ import annotations

import builtins
import inspect
import subprocess
import sys
from typing import Any

import pytest
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from PIL import features as pil_features

from maatlog.image_contracts import (
    DEFAULT_ENCODER_PROFILE,
    IMAGE_BACKEND_MISSING,
    BackendInfo,
    EncoderProfile,
    ImageFormat,
    ImageProcessingError,
)
from maatlog.responsive_images import PIPELINE_SCHEMA, PillowImageVariantGenerator


def test_import_and_constructor_do_not_load_pillow() -> None:
    # Absolute-zero is unattainable: maatlog/__init__ -> extension -> sphinx ->
    # docutils.parsers.rst.directives.images imports PIL when Pillow is
    # installed, and that chain is outside this task's editable files. The
    # warm-up import below loads that shared chain first, so the assertion
    # measures only what this module and its constructor add: nothing.
    code = (
        "import sys; "
        "import maatlog.image_contracts; "
        'before = {n for n in sys.modules if n == "PIL" or n.startswith("PIL.")}; '
        "from maatlog.responsive_images import PillowImageVariantGenerator; "
        "PillowImageVariantGenerator(); "
        'after = {n for n in sys.modules if n == "PIL" or n.startswith("PIL.")}; '
        "assert after == before, sorted(after - before)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_pillow_guard_restores_evicted_modules_with_identical_objects() -> None:
    # Proves the shared guard's mechanism in isolation: after an eviction like
    # the disabled-build contract test performs, the helper re-registers the
    # exact collection-time objects, so collection-time references and lazy
    # production imports agree again. Self-contained in either run order.
    from fixtures.responsive_images.pillow_guard import restore_pillow_modules

    original = sys.modules["PIL.features"]
    sys.modules.pop("PIL.features")
    assert "PIL.features" not in sys.modules
    restore_pillow_modules()
    assert sys.modules["PIL.features"] is original


def test_pipeline_schema_is_one() -> None:
    assert PIPELINE_SCHEMA == 1


def test_constructor_takes_keyword_only_encoder_with_default() -> None:
    parameter = inspect.signature(PillowImageVariantGenerator.__init__).parameters["encoder"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is DEFAULT_ENCODER_PROFILE


def test_constructor_rejects_positional_encoder() -> None:
    with pytest.raises(TypeError):
        PillowImageVariantGenerator(DEFAULT_ENCODER_PROFILE)  # type: ignore[misc]


def test_constructor_stores_encoder() -> None:
    custom = EncoderProfile(profile_id="test-encoder")
    assert PillowImageVariantGenerator().encoder is DEFAULT_ENCODER_PROFILE
    assert PillowImageVariantGenerator(encoder=custom).encoder is custom


def test_backend_reports_codec_implementation_versions() -> None:
    backend = PillowImageVariantGenerator().describe_backend()
    assert backend.backend_id == "pillow"
    assert backend.pipeline_schema == 1
    assert ImageFormat.PNG in backend.supported_formats
    assert {"jpg", "zlib", "webp", "libjpeg_turbo", "zlib_ng", "littlecms2"} <= dict(backend.codec_versions).keys()
    assert backend.codec_versions == tuple(sorted(backend.codec_versions))


def test_backend_reports_all_fields() -> None:
    import PIL

    backend = PillowImageVariantGenerator().describe_backend()
    assert isinstance(backend, BackendInfo)
    assert backend.backend_id == "pillow"
    assert backend.backend_version == PIL.__version__
    assert backend.pipeline_schema == PIPELINE_SCHEMA
    assert backend.supported_formats == frozenset({ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP})
    assert len(backend.codec_versions) == 6
    assert all(isinstance(version, str) and version for _, version in backend.codec_versions)


def test_missing_backend_reports_install_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in sys.modules if n == "PIL" or n.startswith("PIL.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = builtins.__import__

    def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ImageProcessingError) as excinfo:
        PillowImageVariantGenerator().describe_backend()
    diagnostic = excinfo.value.diagnostic
    assert diagnostic.code == IMAGE_BACKEND_MISSING
    assert diagnostic.message == "Responsive image backend is unavailable"
    assert diagnostic.field == "maatlog_responsive_images"
    assert diagnostic.expected == 'pip install "maatlog[images]"'


def test_core_init_failure_reports_backend_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_check_codec(name: str) -> bool:
        del name
        raise OSError("cannot initialize image core")

    monkeypatch.setattr(pil_features, "check_codec", failing_check_codec)
    with pytest.raises(ImageProcessingError) as excinfo:
        PillowImageVariantGenerator().describe_backend()
    assert excinfo.value.diagnostic.code == IMAGE_BACKEND_MISSING


def test_missing_jpeg_codec_drops_jpeg_support(monkeypatch: pytest.MonkeyPatch) -> None:
    real_check_codec = pil_features.check_codec

    def check_codec(name: str) -> bool:
        if name == "jpg":
            return False
        return real_check_codec(name)

    monkeypatch.setattr(pil_features, "check_codec", check_codec)
    backend = PillowImageVariantGenerator().describe_backend()
    assert ImageFormat.JPEG not in backend.supported_formats
    assert ImageFormat.PNG in backend.supported_formats
    assert ("jpg", "absent") in backend.codec_versions


def test_missing_webp_module_drops_webp_support(monkeypatch: pytest.MonkeyPatch) -> None:
    real_check_module = pil_features.check_module

    def check_module(name: str) -> bool:
        if name == "webp":
            return False
        return real_check_module(name)

    monkeypatch.setattr(pil_features, "check_module", check_module)
    backend = PillowImageVariantGenerator().describe_backend()
    assert ImageFormat.WEBP not in backend.supported_formats
    assert ("webp", "absent") in backend.codec_versions


def test_missing_littlecms2_keeps_backend_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    real_check_module = pil_features.check_module

    def check_module(name: str) -> bool:
        if name == "littlecms2":
            return False
        return real_check_module(name)

    monkeypatch.setattr(pil_features, "check_module", check_module)
    backend = PillowImageVariantGenerator().describe_backend()
    assert backend.supported_formats == frozenset({ImageFormat.JPEG, ImageFormat.PNG, ImageFormat.WEBP})
    assert ("littlecms2", "absent") in backend.codec_versions


def test_unreadable_version_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    real_version = pil_features.version

    def version(name: str) -> str | None:
        if name == "jpg":
            return None
        return real_version(name)

    monkeypatch.setattr(pil_features, "version", version)
    backend = PillowImageVariantGenerator().describe_backend()
    assert ImageFormat.JPEG in backend.supported_formats
    assert ("jpg", "unavailable") in backend.codec_versions


def test_all_codecs_missing_keeps_backend_with_empty_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    def check_codec(name: str) -> bool:
        del name
        return False

    def check_module(name: str) -> bool:
        del name
        return False

    monkeypatch.setattr(pil_features, "check_codec", check_codec)
    monkeypatch.setattr(pil_features, "check_module", check_module)
    backend = PillowImageVariantGenerator().describe_backend()
    assert backend.backend_id == "pillow"
    assert backend.supported_formats == frozenset()

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError
from sphinx.application import Sphinx

from maatlog.errors import MaatlogBuildError
from maatlog.theme_api import (
    CORE_THEME_API,
    ThemeApiVersion,
    ThemeImplementation,
    ThemeManifest,
    is_compatible,
    load_maatlog_section,
    parse_and_validate_manifest,
    validate_selected_theme,
)


@pytest.mark.parametrize(
    ("manifest", "code"),
    [
        ({}, "maatlog.theme.manifest-invalid"),
        ({"api": "2.0", "implementation": "standalone"}, "maatlog.theme.api-incompatible"),
        ({"api": "1.1", "implementation": "standalone"}, "maatlog.theme.api-incompatible"),
        ({"api": "1.0", "implementation": "unknown"}, "maatlog.theme.manifest-invalid"),
    ],
)
def test_invalid_manifest(manifest: dict[str, Any], code: str) -> None:
    with pytest.raises(MaatlogBuildError, match=code):
        parse_and_validate_manifest(manifest, core_api=ThemeApiVersion(major=1, minor=0))


def test_manifest_invalid_diagnostic_includes_theme_chain_and_core() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        parse_and_validate_manifest(
            {},
            core_api=ThemeApiVersion(major=1, minor=0),
            theme_name="demo-theme",
            inheritance_chain=("demo-theme", "basic"),
        )

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.theme.manifest-invalid"
    assert diagnostic.source == "demo-theme"
    assert "chain=demo-theme,basic" in diagnostic.message
    assert "core_api=1.0" in diagnostic.message


def test_api_incompatible_diagnostic_includes_theme_chain_core_and_theme_api() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        parse_and_validate_manifest(
            {"api": "2.0", "implementation": "standalone"},
            core_api=ThemeApiVersion(major=1, minor=0),
            theme_name="demo-theme",
            inheritance_chain=("demo-theme", "basic"),
        )

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.theme.api-incompatible"
    assert diagnostic.source == "demo-theme"
    assert diagnostic.value == "2.0"
    assert diagnostic.expected == "major=1 and minor<=0"
    assert "chain=demo-theme,basic" in diagnostic.message
    assert "core_api=1.0" in diagnostic.message
    assert "theme_api=2.0" in diagnostic.message


def test_valid_manifest_inherits_base() -> None:
    manifest = parse_and_validate_manifest(
        {"api": "1.0", "implementation": "inherits-base"},
        core_api=ThemeApiVersion(major=1, minor=0),
    )

    assert manifest == ThemeManifest(
        api=ThemeApiVersion(major=1, minor=0),
        implementation=ThemeImplementation.INHERITS_BASE,
    )


def test_valid_manifest_standalone() -> None:
    manifest = parse_and_validate_manifest(
        {"api": "1.0", "implementation": "standalone", "future_key": True},
        core_api=CORE_THEME_API,
    )

    assert manifest.api == ThemeApiVersion(major=1, minor=0)
    assert manifest.implementation is ThemeImplementation.STANDALONE


def test_core_is_compatible_with_equal_or_lower_minor() -> None:
    core = ThemeApiVersion(major=1, minor=2)

    assert is_compatible(core, ThemeApiVersion(major=1, minor=0))
    assert is_compatible(core, ThemeApiVersion(major=1, minor=2))
    assert not is_compatible(core, ThemeApiVersion(major=1, minor=3))
    assert not is_compatible(core, ThemeApiVersion(major=2, minor=0))


def test_load_maatlog_section_reads_toml() -> None:
    section = load_maatlog_section(
        """
        [maatlog]
        api = "1.0"
        implementation = "standalone"
        ignored = 1
        """
    )

    assert section["api"] == "1.0"
    assert section["implementation"] == "standalone"
    parsed = parse_and_validate_manifest(section, core_api=CORE_THEME_API)
    assert parsed.implementation is ThemeImplementation.STANDALONE


def test_load_maatlog_section_requires_table() -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.theme.manifest-invalid"):
        load_maatlog_section('api = "1.0"\n')


def test_validate_selected_theme_hard_fails_missing_manifest(tmp_path: Path) -> None:
    """Final theme without maatlog-theme.toml raises manifest-missing."""
    theme_root = tmp_path / "alabaster"
    theme_root.mkdir()
    assert not (theme_root / "maatlog-theme.toml").exists()

    theme = SimpleNamespace(name="alabaster", get_theme_dirs=lambda: [str(theme_root)])
    builder = SimpleNamespace(name="html", theme=theme)
    app = SimpleNamespace(builder=builder)

    with pytest.raises(MaatlogBuildError, match="maatlog.theme.manifest-missing"):
        validate_selected_theme(cast(Sphinx, app))


def test_theme_models_are_frozen_pydantic() -> None:
    version = ThemeApiVersion(major=1, minor=0)
    manifest = ThemeManifest(api=version, implementation=ThemeImplementation.STANDALONE)

    assert isinstance(version, BaseModel)
    assert isinstance(manifest, BaseModel)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        field_name = "major"
        setattr(version, field_name, 2)


def test_required_contract_constants() -> None:
    from maatlog.theme_api import REQUIRED_BLOCKS, REQUIRED_TEMPLATES

    assert "maatlog/post.html" in REQUIRED_TEMPLATES
    assert "maatlog/archive.html" in REQUIRED_TEMPLATES
    assert len(REQUIRED_BLOCKS) == 9
    assert "maatlog_post_body" in REQUIRED_BLOCKS
    assert "maatlog_sidebar" in REQUIRED_BLOCKS

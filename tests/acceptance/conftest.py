"""Pytest fixtures for the MaatLog acceptance suite."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from acceptance.magazine import MAGAZINE_PROJECT_ROOT
from acceptance.site import AcceptanceSite

if TYPE_CHECKING:
    import importlib.util

    _tests_conftest = Path(__file__).resolve().parent.parent / "conftest.py"
    _spec = importlib.util.spec_from_file_location("_maatlog_tests_conftest", _tests_conftest)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    ProjectFactory = _module.ProjectFactory

__all__ = ["AcceptanceSite", "magazine_site", "site"]


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    return AcceptanceSite(tmp_path / "acceptance", monkeypatch)


@pytest.fixture
def magazine_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    """Magazine 専用 fixture プロジェクトのビルドドライバ。"""
    return AcceptanceSite(tmp_path / "magazine", monkeypatch, project_root=MAGAZINE_PROJECT_ROOT)

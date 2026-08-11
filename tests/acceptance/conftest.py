"""Pytest fixtures for the MaatLog acceptance suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from acceptance.site import AcceptanceSite

__all__ = ["AcceptanceSite", "site"]


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    return AcceptanceSite(tmp_path / "acceptance", monkeypatch)

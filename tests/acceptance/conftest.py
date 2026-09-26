"""Pytest fixtures for the MaatLog acceptance suite."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from acceptance.built_sites import BuiltSite, BuiltSites, SiteKey
from acceptance.magazine import MAGAZINE_PROJECT_ROOT
from acceptance.real_built_sites import RealSites
from acceptance.site import DEFAULT_SOURCE_DATE_EPOCH, PROJECT_ROOT, AcceptanceSite, build_acceptance_site
from acceptance.width_contract import WIDTH_CONTRACT_PROJECT_ROOT
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    import importlib.util

    from playwright.sync_api import Browser

    _tests_conftest = Path(__file__).resolve().parent.parent / "conftest.py"
    _spec = importlib.util.spec_from_file_location("_maatlog_tests_conftest", _tests_conftest)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    ProjectFactory = _module.ProjectFactory

__all__ = [
    "AcceptanceSite",
    "built_site",
    "built_sites",
    "built_width_contract_site",
    "magazine_site",
    "real_sites",
    "shared_browser",
    "site",
    "width_contract_site",
]


@pytest.fixture(scope="session")
def built_sites(tmp_path_factory: pytest.TempPathFactory) -> Generator[BuiltSites]:
    """Worker-local lazy cache of immutable build outputs and HTTP servers."""
    with BuiltSites(tmp_path_factory.mktemp("built-sites")) as sites:
        yield sites


@pytest.fixture(scope="session")
def built_site(built_sites: BuiltSites) -> Callable[..., BuiltSite]:
    """Return shared builds of the repository's fixed acceptance project."""

    def get(
        builder: str = "html",
        *,
        theme: str | None = None,
        config_overrides: Mapping[str, object] | None = None,
        source_date_epoch: str = DEFAULT_SOURCE_DATE_EPOCH,
    ) -> BuiltSite:
        key = SiteKey(
            fixture="acceptance",
            input_id="fixed-project-v1",
            builder=builder,
            theme=theme,
            config=config_overrides,
            source_date_epoch=source_date_epoch,
            responsive_images=False,
            project_root=PROJECT_ROOT,
        )
        return built_sites.get(
            key,
            build_acceptance_site(key, config_overrides=config_overrides),
        )

    return get


@pytest.fixture(scope="session")
def built_width_contract_site(built_sites: BuiltSites) -> Callable[..., BuiltSite]:
    """Return shared builds of the frozen width-contract project (Issue #314)."""

    def get(
        builder: str = "html",
        *,
        theme: str | None = None,
        config_overrides: Mapping[str, object] | None = None,
        source_date_epoch: str = DEFAULT_SOURCE_DATE_EPOCH,
        warningiserror: bool = True,
    ) -> BuiltSite:
        key = SiteKey(
            fixture="width-contract",
            input_id="width-contract-v1",
            builder=builder,
            theme=theme,
            config=config_overrides,
            source_date_epoch=source_date_epoch,
            responsive_images=False,
            warningiserror=warningiserror,
            project_root=WIDTH_CONTRACT_PROJECT_ROOT,
        )
        return built_sites.get(
            key,
            build_acceptance_site(key, config_overrides=config_overrides),
        )

    return get


@pytest.fixture(scope="session")
def real_sites(built_sites: BuiltSites) -> RealSites:
    """遅延生成される実画像サイトの共有プロバイダ（Issue #315）。"""
    return RealSites(built_sites)


@pytest.fixture(scope="module")
def shared_browser() -> Generator[Browser]:
    """モジュールごとに1回だけ起動する共有 Chromium（Issue #313）。

    BrowserContext は共有しない。各ケースが必要なオプションで ``new_context()`` し、
    必ず自分で閉じる。モジュール終了時に ``browser.close()`` と Playwright
    停止が行われる。

    未移行のテストが自前で ``with sync_playwright()`` を開始する間は、この
    fixture の Playwright インスタンスを生かしたままにできない（同一スレッドで
    2つの sync API インスタンスを重ねられない）。そのため scope は module とし、
    module を抜けた時点で確実に停止する。
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    return AcceptanceSite(tmp_path / "acceptance", monkeypatch)


@pytest.fixture
def magazine_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    """Magazine 専用 fixture プロジェクトのビルドドライバ。"""
    return AcceptanceSite(tmp_path / "magazine", monkeypatch, project_root=MAGAZINE_PROJECT_ROOT)


@pytest.fixture
def width_contract_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    """内容幅と layout shell の幅を検証する共有 fixture プロジェクトのビルドドライバ（Issue #202 で凍結）。"""
    return AcceptanceSite(tmp_path / "width-contract", monkeypatch, project_root=WIDTH_CONTRACT_PROJECT_ROOT)

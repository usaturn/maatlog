"""Issue #202: 表 wrapper の DOM 契約（共有 fixture・JS 無効・キーボード・無害性）。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from acceptance.width_contract import (
    OVERFLOW_TOLERANCE_PX,
    WRAPPER_SELECTOR,
    document_overflow,
)
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.conftest import AcceptanceSite

WRAPPER_START = '<div class="maatlog-table-wrapper" tabindex="0">'
DOCUTILS_TABLE = re.compile(r'<table[^>]*class="[^"]*\bdocutils\b')

#: fixture の tables.html に入る docutils 表の数（fixture 凍結値）。
TABLES_PAGE_WRAPPER_COUNT = 7
#: 表を含むページ（blog/index/prose/code には docutils 表が無い）。
TABLE_PAGES = ("tables.html", "normal.html", "mdpage.html", "posts/width-post.html")
FIXTURE_PAGES = (
    "index.html",
    "tables.html",
    "code.html",
    "prose.html",
    "normal.html",
    "mdpage.html",
    "posts/width-post.html",
    "blog.html",
)


def test_width_contract_fixture_builds_wrapped_and_clean(width_contract_site: AcceptanceSite) -> None:
    # warningiserror=True の AcceptanceSite で警告なくビルドできること自体が fixture の契約。
    result = width_contract_site.build("html", theme="maatlog-default")

    for page in FIXTURE_PAGES:
        assert result.path(page).is_file(), page

    for page in TABLE_PAGES:
        text = result.path(page).read_text(encoding="utf-8")
        assert text.count(WRAPPER_START) == len(DOCUTILS_TABLE.findall(text)), page
        assert text.count(WRAPPER_START) >= 1, page

    tables = result.path("tables.html").read_text(encoding="utf-8")
    assert tables.count(WRAPPER_START) == TABLES_PAGE_WRAPPER_COUNT


def test_width_contract_fixture_builds_dirhtml(width_contract_site: AcceptanceSite) -> None:
    result = width_contract_site.build("dirhtml", theme="maatlog-default")

    text = result.path("tables/index.html").read_text(encoding="utf-8")
    assert text.count(WRAPPER_START) == TABLES_PAGE_WRAPPER_COUNT


def test_width_contract_fixture_builds_on_base(width_contract_site: AcceptanceSite) -> None:
    # 共有 DOM 変更が base 直接利用のビルドを壊さないこと（CSS は無変更のまま）。
    result = width_contract_site.build("html", theme="maatlog-base")

    text = result.path("tables.html").read_text(encoding="utf-8")
    assert text.count(WRAPPER_START) == TABLES_PAGE_WRAPPER_COUNT


def test_derived_theme_build_keeps_the_wrapper(site: AcceptanceSite) -> None:
    # api = "1.0" の inherits-base 派生テーマ（acceptance project の contract_theme）。
    result = site.build("html", theme="contract_theme")

    assert WRAPPER_START in result.path("guide.html").read_text(encoding="utf-8")


@pytest.mark.browser
def test_wrappers_exist_with_javascript_disabled(width_contract_site: AcceptanceSite) -> None:
    result = width_contract_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            java_script_enabled=False,
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        try:
            page.goto(result.path("tables.html").resolve().as_uri(), wait_until="load")

            wrappers = page.locator(WRAPPER_SELECTOR)
            assert wrappers.count() == TABLES_PAGE_WRAPPER_COUNT
            assert wrappers.first.get_attribute("tabindex") == "0"
            # すべての docutils 表が wrapper の直下にある（二重ラップなし・漏れなし）。
            assert (
                page.locator(f"{WRAPPER_SELECTOR} > table.docutils").count() == page.locator("table.docutils").count()
            )
        finally:
            context.close()
            browser.close()


@pytest.mark.browser
def test_wrapper_is_keyboard_focusable(width_contract_site: AcceptanceSite) -> None:
    result = width_contract_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        try:
            page.goto(result.path("tables.html").resolve().as_uri(), wait_until="load")

            page.locator(WRAPPER_SELECTOR).first.focus()

            assert page.evaluate("document.activeElement.className") == "maatlog-table-wrapper"
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_wrapper_adds_no_document_overflow(width_contract_site: AcceptanceSite) -> None:
    # 無害な基盤: wrapper 追加だけで新たな横溢れを作らない（幅広表は内部スクロール）。
    result = width_contract_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((390, 844), (1280, 720)):
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path("tables.html").resolve().as_uri(), wait_until="load")

                    assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX, width
                finally:
                    page.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_base_theme_wrapper_exists_with_javascript_disabled(width_contract_site: AcceptanceSite) -> None:
    result = width_contract_site.build("html", theme="maatlog-base")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            java_script_enabled=False,
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        try:
            page.goto(result.path("tables.html").resolve().as_uri(), wait_until="load")

            assert page.locator(WRAPPER_SELECTOR).count() == TABLES_PAGE_WRAPPER_COUNT
        finally:
            context.close()
            browser.close()

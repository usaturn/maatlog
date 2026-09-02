"""パレットプリセットの受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

PAGE = "index.html"

# neon パレットの背景色。3 ブロックすべてを通って body に届く。
NEON_LIGHT_BACKGROUND = "rgb(247, 242, 246)"
NEON_DARK_BACKGROUND = "rgb(11, 7, 16)"


def _background(page: Page) -> str:
    return page.evaluate("() => getComputedStyle(document.body).backgroundColor")


@pytest.mark.browser
def test_selected_palette_paints_the_page_in_both_themes(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default", config_overrides={"maatlog_palette": "neon"})

    assert result.exists("_static/palettes/neon.css")
    assert "_static/palettes/neon.css" in result.text(PAGE)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme="dark")
            page = context.new_page()
            page.goto(result.path(PAGE).resolve().as_uri(), wait_until="load")

            # OS がダーク、data-theme は未設定 → media クエリ側のブロックが効く。
            assert page.get_attribute("html", "data-theme") is None
            assert _background(page) == NEON_DARK_BACKGROUND

            page.click(".maatlog-theme-toggle")

            # 明示的な選択 → :root（パレット側）が効く。
            assert page.get_attribute("html", "data-theme") == "light"
            assert _background(page) == NEON_LIGHT_BACKGROUND

            page.click(".maatlog-theme-toggle")

            # 明示的なダーク → :root[data-theme="dark"]（パレット側）が効く。
            assert page.get_attribute("html", "data-theme") == "dark"
            assert _background(page) == NEON_DARK_BACKGROUND

            context.close()
        finally:
            browser.close()

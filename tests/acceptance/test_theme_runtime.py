"""共有 enhancer registry の実ブラウザ契約（Issue #63 の基盤）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

FIRST_PAGE = "index.html"

# 適用回数を数える probe。enhance() を二度呼んでも 1 回しか増えないこと。
_COUNTING_PROBE = """
() => {
  window.__probe = 0;
  window.maatlog.registerEnhancer("probe", {
    selector: ".maatlog-post-card",
    apply: () => {
      window.__probe += 1;
    },
  });
}
"""

# 例外を投げる probe。ページと他の enhancer を巻き込まないこと。
_THROWING_PROBE = """
() => {
  window.maatlog.registerEnhancer("boom", {
    selector: ".maatlog-banner",
    apply: () => {
      throw new Error("boom");
    },
  });
  window.maatlog.enhance(document);
}
"""


def _card_count(page: Page) -> int:
    return page.evaluate("() => document.querySelectorAll('.maatlog-post-card').length")


@pytest.mark.browser
def test_the_registry_applies_each_enhancer_once_per_element(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")
            cards = _card_count(page)
            assert cards > 0

            page.evaluate(_COUNTING_PROBE)
            page.evaluate("() => window.maatlog.enhance(document)")
            page.evaluate("() => window.maatlog.enhance(document)")

            assert page.evaluate("() => window.__probe") == cards
        finally:
            browser.close()


@pytest.mark.browser
def test_a_throwing_enhancer_does_not_break_the_page(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context(color_scheme="dark").new_page()
            page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")

            page.evaluate(_THROWING_PROBE)

            # 例外を投げた enhancer の隣で、既存機能がそのまま動く。
            page.click(".maatlog-theme-toggle")
            assert page.get_attribute("html", "data-theme") == "light"
        finally:
            browser.close()


@pytest.mark.browser
def test_the_built_site_can_be_served_over_http(site: AcceptanceSite) -> None:
    # fetch() は file:// では必ず失敗する。Infinite Scroll の検証には HTTP が要る。
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}blog.html", wait_until="load")
                status = page.evaluate("async () => (await fetch('blog.html', { credentials: 'same-origin' })).status")

            assert status == 200
            assert page.query_selector(".maatlog-pagination") is not None
        finally:
            browser.close()

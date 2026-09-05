"""Issue #61: Back to Top の実ブラウザ挙動。"""

from __future__ import annotations

import pytest
from acceptance.server import serve_directory
from acceptance.site import AcceptanceSite
from playwright.sync_api import Page, expect, sync_playwright

PAGE = "index.html"
# 閾値の判定だけを見たいので、本文の実際の長さに依存しない高さを与える。
TALL_BODY = "() => { document.body.style.minHeight = '4000px'; }"


def _prepare(page: Page, base_url: str, *, width: int = 1280, height: int = 800) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}{PAGE}", wait_until="load")
    page.evaluate(TALL_BODY)


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_button_appears_past_the_threshold_and_hides_again(site: AcceptanceSite, theme: str) -> None:
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url)
                button = page.locator(".maatlog-back-to-top")

                expect(button).to_be_hidden()

                page.evaluate("() => window.scrollTo(0, 700)")
                expect(button).to_be_visible()

                page.evaluate("() => window.scrollTo(0, 0)")
                expect(button).to_be_hidden()
        finally:
            browser.close()


@pytest.mark.browser
def test_threshold_boundary_is_600px(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url)
                button = page.locator(".maatlog-back-to-top")

                page.evaluate("() => window.scrollTo(0, 599)")
                expect(button).to_be_hidden()

                page.evaluate("() => window.scrollTo(0, 600)")
                expect(button).to_be_visible()
        finally:
            browser.close()


@pytest.mark.browser
def test_click_returns_to_the_top(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url)
                page.evaluate("() => window.scrollTo(0, 1200)")
                page.locator(".maatlog-back-to-top").click()

                page.wait_for_function("() => window.scrollY === 0")
        finally:
            browser.close()


@pytest.mark.browser
def test_click_jumps_without_animation_under_reduced_motion(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context(reduced_motion="reduce").new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url)
                page.evaluate("() => window.scrollTo(0, 1200)")
                page.locator(".maatlog-back-to-top").click()

                # アニメーションを挟まないので、直後には先頭へ着いている。
                assert page.evaluate("() => window.scrollY") == 0
        finally:
            browser.close()


@pytest.mark.browser
def test_keyboard_activation_moves_focus_to_the_top(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url)
                page.evaluate("() => window.scrollTo(0, 1200)")
                page.locator(".maatlog-back-to-top").focus()
                page.keyboard.press("Enter")

                page.wait_for_function("() => window.scrollY === 0")
                # フォーカスが隠れたボタンに取り残されないこと。
                assert page.evaluate("() => document.activeElement.className") != "maatlog-back-to-top"
                assert page.evaluate("() => document.activeElement.classList.contains('maatlog-banner')")
        finally:
            browser.close()


@pytest.mark.browser
def test_mobile_button_clears_the_sidebar_toggle_and_hides_with_the_drawer(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url, width=375, height=812)
                page.evaluate("() => window.scrollTo(0, 1200)")
                button = page.locator(".maatlog-back-to-top")
                expect(button).to_be_visible()

                toggle_box = page.locator(".maatlog-sidebar-toggle").bounding_box()
                button_box = button.bounding_box()
                assert toggle_box is not None
                assert button_box is not None
                overlaps_x = (
                    button_box["x"] < toggle_box["x"] + toggle_box["width"]
                    and toggle_box["x"] < button_box["x"] + button_box["width"]
                )
                overlaps_y = (
                    button_box["y"] < toggle_box["y"] + toggle_box["height"]
                    and toggle_box["y"] < button_box["y"] + button_box["height"]
                )
                assert not (overlaps_x and overlaps_y)
                # タップターゲットの下限 44px。
                assert button_box["width"] >= 44
                assert button_box["height"] >= 44

                page.locator(".maatlog-sidebar-toggle").click()
                expect(button).to_be_hidden()
        finally:
            browser.close()


@pytest.mark.browser
def test_button_stays_absent_without_javascript(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context(java_script_enabled=False).new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{PAGE}", wait_until="load")

                expect(page.locator(".maatlog-back-to-top")).to_be_hidden()
        finally:
            browser.close()


@pytest.mark.browser
def test_restored_scroll_position_shows_the_button_on_load(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _prepare(page, base_url)
                page.evaluate("() => window.scrollTo(0, 1500)")

                # リロードではブラウザがスクロール位置を復元する。scroll イベントは
                # 飛ばないので、enhancer 適用時の update() と pageshow が頼りになる。
                page.reload(wait_until="load")
                page.wait_for_function("() => window.scrollY >= 600")

                expect(page.locator(".maatlog-back-to-top")).to_be_visible()
        finally:
            browser.close()

"""Issue #58 の受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

ColorScheme = Literal["light", "dark"]

FIRST_PAGE = "index.html"
SECOND_PAGE = "posts/rst-post.html"
# The only acceptance page carrying a highlighted block.
CODE_PAGE = "guide.html"


def _effective_theme(page: Page) -> str:
    """<html> に data-theme が無ければ OS 設定が実効テーマ。"""
    return page.evaluate(
        """
        () => {
          const attribute = document.documentElement.dataset.theme;
          if (attribute === "light" || attribute === "dark") {
            return attribute;
          }
          return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        }
        """
    )


def _background(page: Page) -> str:
    return page.evaluate("() => getComputedStyle(document.body).backgroundColor")


@pytest.mark.browser
def test_first_visit_follows_the_operating_system_setting(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch()
        try:
            cases: tuple[tuple[ColorScheme, str], ...] = (
                ("dark", "dark"),
                ("light", "light"),
            )
            for scheme, expected in cases:
                context = browser.new_context(color_scheme=scheme)
                page = context.new_page()
                page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")

                assert page.get_attribute("html", "data-theme") is None
                assert _effective_theme(page) == expected

                context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_toggle_switches_the_theme_without_a_reload(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme="dark")
            page = context.new_page()
            page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")
            before = _background(page)

            page.click(".maatlog-theme-toggle")

            assert page.get_attribute("html", "data-theme") == "light"
            assert _background(page) != before
            assert page.get_attribute(".maatlog-theme-toggle", "aria-pressed") == "false"

            page.click(".maatlog-theme-toggle")

            assert page.get_attribute("html", "data-theme") == "dark"
            assert page.get_attribute(".maatlog-theme-toggle", "aria-pressed") == "true"

            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_choice_is_stored_and_survives_reload_and_navigation(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme="dark")
            page = context.new_page()
            page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")
            page.click(".maatlog-theme-toggle")

            assert page.evaluate("() => window.localStorage.getItem('maatlog-theme')") == "light"

            page.reload(wait_until="load")
            assert page.get_attribute("html", "data-theme") == "light"

            page.goto(result.path(SECOND_PAGE).resolve().as_uri(), wait_until="load")
            assert page.get_attribute("html", "data-theme") == "light"

            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_toggle_is_reachable_and_operable_with_the_keyboard(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme="dark")
            page = context.new_page()
            page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")

            page.focus(".maatlog-theme-toggle")
            page.keyboard.press("Enter")

            assert page.get_attribute("html", "data-theme") == "light"

            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_without_javascript_the_os_setting_still_governs(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            dark = browser.new_context(color_scheme="dark", java_script_enabled=False)
            dark_page = dark.new_page()
            dark_page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")
            dark_background = _background(dark_page)

            light = browser.new_context(color_scheme="light", java_script_enabled=False)
            light_page = light.new_page()
            light_page.goto(result.path(FIRST_PAGE).resolve().as_uri(), wait_until="load")
            light_background = _background(light_page)

            assert dark_background != light_background
            # 押しても何も起きないボタンを見せない。
            assert dark_page.is_hidden(".maatlog-theme-toggle")

            dark.close()
            light.close()
        finally:
            browser.close()


def _code_colours(page: Page) -> dict[str, str]:
    """Computed colours of the highlighted block, straight from Pygments."""
    return page.evaluate(
        """
        () => {
          const pre = document.querySelector(".highlight pre");
          const keyword = document.querySelector(".highlight .k");
          const style = getComputedStyle(pre);
          return {
            background: style.backgroundColor,
            text: style.color,
            keyword: getComputedStyle(keyword).color,
          };
        }
        """
    )


@pytest.mark.browser
def test_code_blocks_follow_the_explicit_choice(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme="light")
            page = context.new_page()
            page.goto(result.path(CODE_PAGE).resolve().as_uri(), wait_until="load")
            light_media = page.get_attribute("#pygments_dark_css", "media")
            light_colours = _code_colours(page)

            page.click(".maatlog-theme-toggle")

            assert light_media == "(prefers-color-scheme: dark)"
            assert page.get_attribute("#pygments_dark_css", "media") == "all"
            # The dark sheet must actually repaint the block, not just be enabled.
            assert _code_colours(page) != light_colours

            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_code_blocks_follow_the_operating_system_setting(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            colours: dict[str, dict[str, str]] = {}
            schemes: tuple[ColorScheme, ...] = ("light", "dark")
            for scheme in schemes:
                context = browser.new_context(color_scheme=scheme)
                page = context.new_page()
                page.goto(result.path(CODE_PAGE).resolve().as_uri(), wait_until="load")
                colours[scheme] = _code_colours(page)
                context.close()

            assert colours["light"] != colours["dark"]
        finally:
            browser.close()

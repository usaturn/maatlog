"""Issue #65: mobile sidebar drawer behaviour in a real browser."""

from __future__ import annotations

import re

import pytest
from acceptance.server import serve_directory
from acceptance.site import AcceptanceSite
from playwright.sync_api import expect, sync_playwright

IS_OPEN = re.compile(r"\bis-open\b")
SIDEBAR_OPEN = re.compile(r"\bmaatlog-sidebar-open\b")
IS_VISIBLE = re.compile(r"\bis-visible\b")


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_mobile_sidebar_open_close_escape_backdrop_focus(site: AcceptanceSite, theme: str) -> None:
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 375, "height": 812})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}index.html", wait_until="load")

                toggle = page.locator(".maatlog-sidebar-toggle")
                sidebar = page.locator("#maatlog-sidebar")
                expect(toggle).to_be_visible()
                expect(toggle).to_have_attribute("aria-expanded", "false")

                toggle.click()
                expect(toggle).to_have_attribute("aria-expanded", "true")
                expect(sidebar).to_have_class(IS_OPEN)
                expect(page.locator("html")).to_have_class(SIDEBAR_OPEN)
                expect(page.locator(".maatlog-sidebar-backdrop")).to_have_class(IS_VISIBLE)
                expect(page.locator("#maatlog-sidebar :focus")).to_be_visible()

                page.keyboard.press("Escape")
                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(sidebar).not_to_have_class(IS_OPEN)
                expect(toggle).to_be_focused()

                toggle.click()
                backdrop = page.locator(".maatlog-sidebar-backdrop")
                expect(backdrop).to_be_visible()
                box = backdrop.bounding_box()
                assert box is not None
                page.mouse.click(box["x"] + box["width"] - 1, box["y"] + box["height"] / 2)
                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(sidebar).not_to_have_class(IS_OPEN)
                expect(toggle).to_be_focused()
        finally:
            browser.close()


@pytest.mark.browser
def test_mobile_sidebar_resets_when_entering_desktop(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 375, "height": 812})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}index.html", wait_until="load")
                page.locator(".maatlog-sidebar-toggle").click()
                expect(page.locator("#maatlog-sidebar")).to_have_class(IS_OPEN)

                page.set_viewport_size({"width": 1280, "height": 800})
                page.wait_for_timeout(100)
                expect(page.locator("#maatlog-sidebar")).not_to_have_class(IS_OPEN)
                expect(page.locator("html")).not_to_have_class(SIDEBAR_OPEN)
                expect(page.locator(".maatlog-sidebar-toggle")).to_be_hidden()
        finally:
            browser.close()


@pytest.mark.browser
def test_mobile_sidebar_toggle_hidden_without_maatlog_js(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 375, "height": 812})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}index.html", wait_until="load")
                page.evaluate("() => document.documentElement.classList.remove('maatlog-js')")
                expect(page.locator(".maatlog-sidebar-toggle")).to_be_hidden()
                expect(page.locator("#maatlog-sidebar")).to_be_attached()
        finally:
            browser.close()


@pytest.mark.browser
def test_mobile_sidebar_focus_trap_holds_at_collapsed_details(site: AcceptanceSite) -> None:
    """A collapsed ``<details>`` at the end of the drawer must not leak focus.

    Without feeds the drawer ends with the archive section, so once its
    ``<details>`` is collapsed the last element in the browser's tab order is
    the ``<summary>`` itself. The trap has to know that.
    """
    result = site.build("html", theme="maatlog-default", config_overrides={"maatlog_generate_feeds": False})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 375, "height": 812})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}index.html", wait_until="load")

                page.locator(".maatlog-sidebar-toggle").click()
                expect(page.locator("#maatlog-sidebar")).to_have_class(IS_OPEN)

                summary = page.locator("#maatlog-sidebar .maatlog-taxonomy-year > summary").last
                summary.click()
                expect(page.locator("#maatlog-sidebar details[open]")).to_have_count(0)
                summary.focus()

                for _ in range(3):
                    page.keyboard.press("Tab")
                    assert page.evaluate(
                        "() => document.querySelector('#maatlog-sidebar').contains(document.activeElement)"
                    ), "focus escaped the drawer"
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_mobile_sidebar_toggle_closes_the_open_drawer(site: AcceptanceSite, theme: str) -> None:
    """Issue #65: pressing the toggle again closes the drawer.

    ``toggle.click()`` drives the element directly, so it cannot see the drawer
    covering the button. Clicking the toggle's coordinates does.
    """
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 375, "height": 812})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}index.html", wait_until="load")
                url_before = page.url

                toggle = page.locator(".maatlog-sidebar-toggle")
                toggle.click()
                expect(page.locator("#maatlog-sidebar")).to_have_class(IS_OPEN)
                page.wait_for_timeout(300)

                box = toggle.bounding_box()
                assert box is not None
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

                expect(toggle).to_have_attribute("aria-expanded", "false")
                expect(page.locator("#maatlog-sidebar")).not_to_have_class(IS_OPEN)
                expect(toggle).to_be_focused()
                assert page.url == url_before
        finally:
            browser.close()

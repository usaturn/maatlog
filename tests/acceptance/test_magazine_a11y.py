"""Magazine Home のアクセシビリティと palette を検証する（Issue #181）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import pytest
from acceptance.accessibility import axe_violations
from acceptance.magazine import HOME_PAGE, PALETTES, card_boxes
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

ROOT = Path(__file__).resolve().parents[2]
AXE_PATH = ROOT / "node_modules" / "axe-core" / "axe.min.js"

ColorScheme = Literal["light", "dark"]


@pytest.mark.browser
@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_magazine_home_has_no_automatic_accessibility_violations(
    magazine_site: AcceptanceSite, color_scheme: ColorScheme
) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme=color_scheme)
            page = context.new_page()
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
            violations = axe_violations(page, AXE_PATH)
            assert violations == [], json.dumps(violations, ensure_ascii=False, indent=2)
            context.close()
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_every_builtin_palette_paints_the_magazine_home(
    magazine_site: AcceptanceSite, palette: str | None, color_scheme: ColorScheme
) -> None:
    overrides: dict[str, object] | None = None if palette is None else {"maatlog_palette": palette}
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=overrides)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme=color_scheme, viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")

            background = cast(str, page.evaluate("() => getComputedStyle(document.body).backgroundColor"))
            assert background not in {"rgba(0, 0, 0, 0)", "transparent"}, f"{palette}/{color_scheme}"

            violations = [item for item in axe_violations(page, AXE_PATH) if item["id"] == "color-contrast"]
            assert violations == [], json.dumps(violations, ensure_ascii=False, indent=2)
            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_only_the_site_name_uses_h1_and_cards_use_h2(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")

            assert page.locator("h1").count() == 1
            card_titles = page.locator(".maatlog-post-card-title").evaluate_all(
                "(nodes) => nodes.map((node) => node.tagName.toLowerCase())"
            )
            assert card_titles and all(tag == "h2" for tag in card_titles)
        finally:
            browser.close()


def _focus_trail(page: Page, presses: int) -> list[str]:
    trail: list[str] = []
    for _ in range(presses):
        page.keyboard.press("Tab")
        trail.append(
            cast(
                str,
                page.evaluate(
                    """
                    () => {
                      const active = document.activeElement;
                      if (!active) return '';
                      const card = active.closest('.maatlog-post-card');
                      return card ? (card.dataset.slug ?? '') : '';
                    }
                    """
                ),
            )
        )
    return [slug for slug in trail if slug]


@pytest.mark.browser
def test_keyboard_order_follows_the_dom_order_of_cards(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
            dom_order = [box["slug"] for box in card_boxes(page)]

            visited = _focus_trail(page, presses=80)
            seen: list[str] = []
            for slug in visited:
                if slug not in seen:
                    seen.append(slug)

            assert seen == dom_order[: len(seen)], f"{seen} != {dom_order}"
            assert seen == dom_order
        finally:
            browser.close()


@pytest.mark.browser
def test_focus_is_visible_on_every_card_link(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
            page.locator(".maatlog-post-card-title a").first.focus()

            outline = cast(
                str,
                page.evaluate(
                    """
                    () => {
                      const style = getComputedStyle(document.activeElement);
                      return `${style.outlineStyle}|${style.outlineWidth}|${style.boxShadow}`;
                    }
                    """
                ),
            )
            assert outline != "none|0px|none", outline
        finally:
            browser.close()


@pytest.mark.browser
def test_reduced_motion_does_not_break_the_magazine_layout(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(reduced_motion="reduce", viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")

            boxes = card_boxes(page)
            assert len(boxes) == 12
            durations = cast(
                list[str],
                page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('.maatlog-post-card'))
                      .map((card) => getComputedStyle(card).transitionDuration)
                    """
                ),
            )
            assert all(value == "0s" for value in durations), durations
            context.close()
        finally:
            browser.close()

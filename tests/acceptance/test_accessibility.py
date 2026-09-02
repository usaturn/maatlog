from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest
from acceptance.accessibility import axe_violations
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

ROOT = Path(__file__).resolve().parents[2]
AXE_PATH = ROOT / "node_modules" / "axe-core" / "axe.min.js"
# guide.html carries the only highlighted code block, so Pygments is audited too.
# home.html is the only page that renders the featured bento.
CORE_PAGES = ("index.html", "home.html", "blog.html", "posts/rst-post.html", "guide.html")

ColorScheme = Literal["light", "dark"]


@pytest.mark.browser
@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_default_theme_core_pages_have_no_automatic_accessibility_violations(
    site: AcceptanceSite, color_scheme: ColorScheme
) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(color_scheme=color_scheme)
            page = context.new_page()
            for relative in CORE_PAGES:
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                violations = axe_violations(page, AXE_PATH)
                assert violations == [], (
                    f"{relative} ({color_scheme}): {json.dumps(violations, ensure_ascii=False, indent=2)}"
                )
            context.close()
        finally:
            browser.close()

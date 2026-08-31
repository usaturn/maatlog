from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from acceptance.accessibility import axe_violations
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

ROOT = Path(__file__).resolve().parents[2]
AXE_PATH = ROOT / "node_modules" / "axe-core" / "axe.min.js"
CORE_PAGES = ("index.html", "blog.html", "posts/rst-post.html")


@pytest.mark.browser
def test_default_theme_core_pages_have_no_automatic_accessibility_violations(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            for relative in CORE_PAGES:
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                violations = axe_violations(page, AXE_PATH)
                assert violations == [], f"{relative}: {json.dumps(violations, ensure_ascii=False, indent=2)}"
        finally:
            browser.close()

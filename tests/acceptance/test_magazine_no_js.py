"""JavaScript を無効にしても Magazine Home の導線が使えることを検証する（Issue #181）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from acceptance.magazine import ARCHIVE_PAGE, HOME_PAGE, PUBLISHED_SLUGS
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite


def _hrefs(page: Page, selector: str) -> list[str]:
    return cast(
        list[str],
        page.evaluate(
            "(selector) => Array.from(document.querySelectorAll(selector)).map((a) => a.getAttribute('href') ?? '')",
            selector,
        ),
    )


@pytest.mark.browser
def test_every_card_links_to_its_post_without_javascript(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")

            titles = _hrefs(page, ".maatlog-post-card-title a")
            assert len(titles) == len(PUBLISHED_SLUGS)
            for slug in PUBLISHED_SLUGS:
                assert any(href.endswith(f"posts/{slug}.html") for href in titles), slug

            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_taxonomy_and_archive_links_work_without_javascript(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")

            taxonomy = [href for href in _hrefs(page, ".maatlog-taxonomy-link") if href]
            assert taxonomy, "no taxonomy links on the magazine home"

            archive = _hrefs(page, ".maatlog-home-archive-link")
            assert archive and archive[0].endswith(ARCHIVE_PAGE)

            # 実際に遷移できることまで確認する（リンク切れの検出）。
            page.click(".maatlog-home-archive-link")
            page.wait_for_load_state("load")
            assert page.url.endswith(ARCHIVE_PAGE)

            context.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_all_home_links_resolve_on_disk(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    assert result.links_are_resolvable(HOME_PAGE)
    assert result.links_are_resolvable(ARCHIVE_PAGE)

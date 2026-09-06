"""Archive がトップを兼ねる経路と、既存ページの回帰を検証する（Issue #181）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from acceptance.magazine import ARCHIVE_PAGE, PAGE_SIZE, PUBLISHED_SLUGS
from acceptance.server import serve_directory
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

# maatlog_home_docname を外すと blog.html が Home を兼ねる。
FALLBACK_OVERRIDES: dict[str, object] = {"maatlog_home_docname": None}


def _slugs(page: Page) -> list[str]:
    return cast(
        list[str],
        page.evaluate(
            """
            () => Array.from(document.querySelectorAll('.maatlog-post-card'))
              .map((element) => element.dataset.slug ?? '')
            """
        ),
    )


def test_fallback_archive_becomes_the_home_page(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=FALLBACK_OVERRIDES)

    assert result.succeeded
    archive = result.html(ARCHIVE_PAGE)
    assert archive.select_one(".maatlog-hero") is not None
    # home.md のソースは残るため home.html 自体は通常ページとして出力されるが、
    # Magazine Home としては扱われない（カードも hero も持たない）。
    if result.exists("home.html"):
        home = result.html("home.html")
        assert home.select_one(".maatlog-hero") is None
        assert home.select(".maatlog-post-card") == []


def test_fallback_page_one_keeps_the_chronological_window(magazine_site: AcceptanceSite) -> None:
    """Featured は投影であり、ページ窓（PAGE_SIZE 件）を縮めない（#177 契約）。"""
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=FALLBACK_OVERRIDES)
    page_one = result.html(ARCHIVE_PAGE)
    slugs = [card["data-slug"] for card in page_one.select(".maatlog-post-card")]

    assert len(slugs) == PAGE_SIZE
    assert len(set(slugs)) == len(slugs)
    assert slugs == list(PUBLISHED_SLUGS[:PAGE_SIZE])


def test_fallback_pagination_covers_every_published_post(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=FALLBACK_OVERRIDES)

    seen: list[str] = []
    for relative in (ARCHIVE_PAGE, "blog/page/2.html"):
        assert result.exists(relative), relative
        seen.extend(card["data-slug"] for card in result.html(relative).select(".maatlog-post-card"))

    assert len(seen) == len(set(seen)), "記事がページ間で重複している"
    assert set(seen) == set(PUBLISHED_SLUGS), "ページ送りで記事が欠落している"


@pytest.mark.browser
def test_fallback_infinite_scroll_appends_without_gaps_or_duplicates(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=FALLBACK_OVERRIDES)
    with serve_directory(result.outdir) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
            first = _slugs(page)
            assert len(first) == PAGE_SIZE

            page.keyboard.press("End")
            page.wait_for_function(
                "(expected) => document.querySelectorAll('.maatlog-post-card').length > expected",
                arg=len(first),
                timeout=10_000,
            )
            appended = _slugs(page)

            assert len(appended) == len(set(appended)), "無限スクロールで記事が重複した"
            assert set(appended) == set(PUBLISHED_SLUGS), "無限スクロールで記事が欠落した"
        finally:
            browser.close()


@pytest.mark.browser
def test_fallback_filter_never_drops_or_duplicates_posts(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=FALLBACK_OVERRIDES)
    with serve_directory(result.outdir) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
            page.wait_for_timeout(200)
            before = _slugs(page)

            # フィルターの発火方法は既存 test_archive_filter.py と同じ操作にする
            # （URL fragment ではなく sidebar のリンククリック）。
            page.click('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="sphinx"]')
            page.wait_for_timeout(200)
            filtered = [
                slug
                for slug in _slugs(page)
                if page.evaluate(
                    '(slug) => { const c = document.querySelector(`.maatlog-post-card[data-slug="${slug}"]`);'
                    " return c !== null && getComputedStyle(c).display !== 'none'"
                    " && c.getBoundingClientRect().height !== 0; }",
                    slug,
                )
            ]

            assert filtered, "タグ絞り込みの結果が空になった"
            assert len(filtered) == len(set(filtered)), "絞り込み結果に重複がある"
            assert set(filtered) <= set(before) | set(PUBLISHED_SLUGS)
        finally:
            browser.close()


def test_regular_surfaces_still_render_in_the_magazine_fixture(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")

    for relative in (
        "blog.html",
        "blog/tag/sphinx.html",
        "blog/category/engineering.html",
        "blog/author/alice.html",
        "search.html",
    ):
        assert result.exists(relative), relative
        assert result.links_are_resolvable(relative), relative

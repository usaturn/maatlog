"""Real-browser behaviour of the right rail across the three breakpoints."""

from __future__ import annotations

import pytest
from acceptance.server import serve_directory
from acceptance.site import AcceptanceSite
from playwright.sync_api import Page, sync_playwright

POST_PAGE = "posts/three-authors.html"
TALL_POST_PAGE = "posts/md-post.html"
LONG_TOC_PAGE = "long-toc.html"
TALL_BIO_MARKER = "TALL-BIO-END"
TALL_BIO_SHORT = "Word. " * 80 + TALL_BIO_MARKER
TALL_AUTHOR_PROFILES = {
    "alice": {
        "role": "Editor & Developer",
        "avatar": "authors/alice.png",
        "bio_short": TALL_BIO_SHORT,
        "interests": ["Python", "Cloud", "Sphinx"],
        "links": [
            {"type": "github", "url": "https://github.com/example"},
            {"type": "website", "url": "https://example.com/"},
        ],
        "about_docname": "authors/alice",
    },
}


def _box(page: Page, selector: str) -> dict[str, float] | None:
    return page.evaluate(
        """(selector) => {
             const element = document.querySelector(selector);
             if (!element) return null;
             const box = element.getBoundingClientRect();
             return {top: box.top, bottom: box.bottom, left: box.left, right: box.right};
           }""",
        selector,
    )


def _toc_slack(page: Page) -> float:
    """``.maatlog-toc`` の下端と、その最後の子要素の下端の差（px）。

    正の値は内容の下に残った空白を意味する。desktop の下限 ``min-height: 8rem``
    が narrow 幅へ漏れると、ここが 0 より大きくなる。
    """
    return page.evaluate(
        """() => {
             const toc = document.querySelector('.maatlog-toc');
             const last = toc.lastElementChild;
             return toc.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom;
           }"""
    )


@pytest.mark.browser
def test_desktop_puts_the_rail_beside_the_content(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                main = _box(page, ".maatlog-layout-main")
                summary = _box(page, ".maatlog-author-summary")

                assert main is not None and summary is not None
                assert summary["left"] >= main["right"] - 2
        finally:
            browser.close()


@pytest.mark.browser
def test_desktop_tall_author_summary_keeps_toc_visible_and_scrolls_the_rail(
    site: AcceptanceSite,
) -> None:
    result = site.build(
        "html",
        theme="maatlog-default",
        config_overrides={"maatlog_author_profiles": TALL_AUTHOR_PROFILES},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 1440, "height": 600})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{TALL_POST_PAGE}", wait_until="load")
                metrics = page.evaluate(
                    """(marker) => {
                         const rail = document.querySelector('.maatlog-right-rail');
                         const toc = document.querySelector('.maatlog-toc');
                         const bio = [...document.querySelectorAll('.maatlog-author-summary-bio')]
                           .find((element) => element.textContent.includes(marker));
                         if (!rail || !toc || !bio) {
                           return { ok: false, reason: 'missing-elements' };
                         }
                         const tocHeight = toc.getBoundingClientRect().height;
                         const scrollable = rail.scrollHeight > rail.clientHeight + 1;
                         rail.scrollTop = rail.scrollHeight;
                         const railBox = rail.getBoundingClientRect();
                         const bioBox = bio.getBoundingClientRect();
                         const markerReachable = bioBox.bottom <= railBox.bottom + 1;
                         const tocLink = toc.querySelector('a');
                         const tocLinkBox = tocLink?.getBoundingClientRect();
                         const tocLinkReachable = !!(
                           tocLinkBox
                           && tocLinkBox.height > 0
                           && tocLinkBox.top >= railBox.top - 1
                           && tocLinkBox.bottom <= railBox.bottom + 1
                         );
                         return {
                           ok: true,
                           tocHeight,
                           scrollable,
                           markerReachable,
                           tocLinkReachable,
                         };
                       }""",
                    TALL_BIO_MARKER,
                )

                assert metrics["ok"] is True
                assert metrics["tocHeight"] > 0
                assert metrics["scrollable"] is True
                assert metrics["markerReachable"] is True
                assert metrics["tocLinkReachable"] is True
        finally:
            browser.close()


@pytest.mark.browser
def test_desktop_scrolls_the_toc_without_moving_the_summary(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 1440, "height": 600})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{LONG_TOC_PAGE}", wait_until="load")
                before = _box(page, ".maatlog-author-summary")
                metrics = page.evaluate(
                    """() => {
                         const toc = document.querySelector('.maatlog-toc');
                         if (!toc) return { tocScrollable: false, tocScrollTop: 0 };
                         const tocScrollable = toc.scrollHeight > toc.clientHeight + 1;
                         toc.scrollTop = 200;
                         return { tocScrollable, tocScrollTop: toc.scrollTop };
                       }"""
                )
                after = _box(page, ".maatlog-author-summary")

                assert before is not None and after is not None
                assert metrics["tocScrollable"] is True
                assert metrics["tocScrollTop"] > 0
                assert before == after
        finally:
            browser.close()


@pytest.mark.browser
def test_tablet_moves_the_rail_above_the_content(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 1024, "height": 768})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                main = _box(page, ".maatlog-layout-main")
                summary = _box(page, ".maatlog-author-summary")

                assert main is not None and summary is not None
                assert summary["bottom"] <= main["top"] + 2
        finally:
            browser.close()


@pytest.mark.browser
def test_mobile_puts_the_summary_after_the_article_and_the_toc_before_it(
    site: AcceptanceSite,
) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 390, "height": 844})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                main = _box(page, ".maatlog-layout-main")
                summary = _box(page, ".maatlog-author-summary")
                toc = _box(page, ".maatlog-toc")

                assert main is not None and summary is not None and toc is not None
                assert toc["bottom"] <= main["top"] + 2
                assert summary["top"] >= main["bottom"] - 2
        finally:
            browser.close()


@pytest.mark.browser
def test_mobile_does_not_pad_a_short_toc(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 390, "height": 844})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")

                # rail が flex コンテナでない幅では、TOC の高さは内容が決める。
                # desktop の下限が漏れると本文の直前に意図の読めない空白が出る。
                assert _toc_slack(page) <= 1
        finally:
            browser.close()


@pytest.mark.browser
def test_the_summary_exists_exactly_once_in_the_dom(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 390, "height": 844})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                count = page.evaluate("document.querySelectorAll('.maatlog-author-summary').length")

                assert count == 1
        finally:
            browser.close()


@pytest.mark.browser
def test_the_disclosure_opens_from_the_keyboard(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                summary = page.locator(".maatlog-author-summary-more > summary")
                summary.focus()
                page.keyboard.press("Enter")

                assert page.locator(".maatlog-author-summary-more").get_attribute("open") is not None
                hidden_link = page.locator(".maatlog-author-summary-more .maatlog-author-summary-profile-link").first
                assert hidden_link.is_visible()
        finally:
            browser.close()


@pytest.mark.browser
def test_the_profile_page_has_no_right_rail_summary(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}blog/author/alice.html", wait_until="load")
                count = page.evaluate("document.querySelectorAll('.maatlog-author-summary').length")

                assert count == 0
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1024, 768), (390, 844)])
def test_the_rail_never_overflows_horizontally(site: AcceptanceSite, width: int, height: int) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.set_viewport_size({"width": width, "height": height})
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

                assert overflow <= 1
        finally:
            browser.close()

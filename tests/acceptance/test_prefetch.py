"""Issue #66 の Prefetch 受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceBuildResult, AcceptanceSite

ARCHIVE_PAGE = "blog.html"
SECOND_PAGE = "blog/page/2.html"
POST_PAGE = "posts/rst-post.html"
GUIDE_PAGE = "guide.html"


def _tall_excerpt(repeat: int = 16) -> str:
    sentence = "Filler copy that pads this card past the fold so the sentinel starts out of view. "
    return (sentence * repeat).strip()


TALL_EXCERPT = _tall_excerpt()

EXTRA_POSTS: dict[str, str] = {
    f"posts/scroll-{number}.rst": (
        ":maatlog-post: true\n"
        f":maatlog-slug: scroll-{number}\n"
        f":maatlog-published-at: 2026-08-0{number}T12:00:00Z\n"
        f":maatlog-excerpt: {TALL_EXCERPT}\n"
        "\n"
        f"Scroll post {number}\n"
        "===================\n"
        "\n"
        f"Filler body {number}.\n"
    )
    for number in (1, 2, 3, 4)
}
EXTRA_POSTS["posts/rst-post.rst"] = (
    ":maatlog-post: true\n"
    ":maatlog-slug: rst-post\n"
    ":maatlog-published-at: 2026-08-10T12:00:00Z\n"
    ":maatlog-tags: sphinx, python\n"
    ":maatlog-categories: engineering\n"
    ":maatlog-authors: alice\n"
    f":maatlog-excerpt: {TALL_EXCERPT}\n"
    ":maatlog-image: cover.png\n"
    "\n"
    "reStructuredText post\n"
    "=====================\n"
    "\n"
    "Body shared with the MyST twin for parser parity.\n"
    "\n"
    "See the :doc:`/guide` and :py:func:`api.greet`.\n"
)
EXTRA_POSTS["posts/md-post.md"] = (
    "---\n"
    "maatlog-post: true\n"
    "maatlog-slug: md-post\n"
    "maatlog-published-at: 2026-08-10T12:00:00Z\n"
    "maatlog-tags: [sphinx, python]\n"
    "maatlog-categories: [engineering]\n"
    "maatlog-authors: [alice]\n"
    f"maatlog-excerpt: {TALL_EXCERPT}\n"
    "maatlog-image: cover.png\n"
    "---\n"
    "# reStructuredText post\n"
    "\n"
    "Body shared with the MyST twin for parser parity.\n"
    "\n"
    "See the {doc}`/guide` and {py:func}`api.greet`.\n"
)

ARCHIVE_CONFIG: dict[str, object] = {
    "maatlog_page_size": 1,
    "suppress_warnings": ["toc.not_included"],
}


def build_paginated_site(site: AcceptanceSite) -> AcceptanceBuildResult:
    return site.build(
        "html",
        theme="maatlog-default",
        config_overrides=ARCHIVE_CONFIG,
        extra_files=EXTRA_POSTS,
    )


def prefetch_hrefs(page: Page) -> list[str]:
    return page.evaluate("() => [...document.querySelectorAll('link[rel=\"prefetch\"]')].map((link) => link.href)")


def absolute_href(page: Page, selector: str) -> str | None:
    return page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          return el instanceof HTMLAnchorElement ? el.href : null;
        }""",
        selector,
    )


def wait_for_prefetch(page: Page, href: str, *, timeout: float = 5000) -> None:
    page.wait_for_function(
        """(target) => [...document.querySelectorAll('link[rel=\"prefetch\"]')]
            .some((link) => link.href === target)""",
        arg=href,
        timeout=timeout,
    )


@pytest.mark.browser
def test_newer_and_older_posts_are_prefetched(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                targets = [
                    href
                    for href in (
                        absolute_href(page, ".maatlog-nav-newer"),
                        absolute_href(page, ".maatlog-nav-older"),
                    )
                    if href is not None
                ]
                assert targets, "fixture post must expose at least one neighbor link"

                for href in targets:
                    wait_for_prefetch(page, href)
        finally:
            browser.close()


@pytest.mark.browser
def test_archive_next_page_is_prefetched(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                next_url = absolute_href(page, ".maatlog-pagination-next")
                assert next_url is not None
                wait_for_prefetch(page, next_url)
        finally:
            browser.close()


@pytest.mark.browser
def test_hover_or_focus_prefetches_an_internal_link(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                guide = absolute_href(page, f'a[href$="{GUIDE_PAGE}"]')
                assert guide is not None

                before = prefetch_hrefs(page)
                assert guide not in before

                page.locator(f'a[href$="{GUIDE_PAGE}"]').first.hover()
                wait_for_prefetch(page, guide)
        finally:
            browser.close()


@pytest.mark.browser
def test_external_links_are_not_prefetched(site: AcceptanceSite) -> None:
    result = site.build(
        "html",
        theme="maatlog-default",
        extra_files={
            "posts/with-external.rst": (
                ":maatlog-post: true\n"
                ":maatlog-slug: with-external\n"
                ":maatlog-published-at: 2026-08-12T12:00:00Z\n"
                "\n"
                "External link post\n"
                "==================\n"
                "\n"
                "`Example <https://example.com/outside>`_\n"
            )
        },
        config_overrides={"suppress_warnings": ["toc.not_included"]},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}posts/with-external.html", wait_until="load")
                external = absolute_href(page, 'a[href^="https://example.com"]')
                assert external is not None

                page.locator('a[href^="https://example.com"]').first.hover()
                page.wait_for_timeout(300)

                assert external not in prefetch_hrefs(page)
        finally:
            browser.close()


@pytest.mark.browser
def test_the_same_url_is_never_prefetched_twice(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                guide = absolute_href(page, f'a[href$="{GUIDE_PAGE}"]')
                assert guide is not None

                locator = page.locator(f'a[href$="{GUIDE_PAGE}"]').first
                locator.hover()
                wait_for_prefetch(page, guide)
                locator.focus()
                page.wait_for_timeout(200)

                matches = [href for href in prefetch_hrefs(page) if href == guide]
                assert len(matches) == 1
        finally:
            browser.close()


@pytest.mark.browser
def test_hash_variants_of_the_same_document_are_prefetched_once(site: AcceptanceSite) -> None:
    result = site.build(
        "html",
        theme="maatlog-default",
        extra_files={
            "posts/hash-prefetch.rst": (
                ":maatlog-post: true\n"
                ":maatlog-slug: hash-prefetch\n"
                ":maatlog-published-at: 2026-08-12T12:00:00Z\n"
                "\n"
                "Hash prefetch\n"
                "=============\n"
                "\n"
                "`Install <../guide.html#install>`_\n"
                "\n"
                "`Usage <../guide.html#usage>`_\n"
            )
        },
        config_overrides={"suppress_warnings": ["toc.not_included"]},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}posts/hash-prefetch.html", wait_until="load")

                install = absolute_href(page, 'a[href$="guide.html#install"]')
                usage = absolute_href(page, 'a[href$="guide.html#usage"]')
                assert install is not None
                assert usage is not None

                page.locator('a[href$="guide.html#install"]').hover()
                page.wait_for_function(
                    """() => [...document.querySelectorAll('link[rel="prefetch"]')]
                        .some((link) => link.href.endsWith("guide.html"))"""
                )
                page.locator('a[href$="guide.html#usage"]').hover()
                page.wait_for_timeout(200)

                guide_matches = [href for href in prefetch_hrefs(page) if "guide.html" in href]
                assert len(guide_matches) == 1
                assert guide_matches[0].endswith(GUIDE_PAGE)
        finally:
            browser.close()


@pytest.mark.browser
def test_save_data_suppresses_prefetch(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            context.add_init_script(
                """
                Object.defineProperty(navigator, "connection", {
                  configurable: true,
                  get: () => ({ saveData: true, effectiveType: "4g" }),
                });
                """
            )
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
                page.wait_for_timeout(300)
                assert prefetch_hrefs(page) == []

                guide = page.locator(f'a[href$="{GUIDE_PAGE}"]').first
                guide.hover()
                page.wait_for_timeout(300)
                assert prefetch_hrefs(page) == []
        finally:
            browser.close()


@pytest.mark.browser
def test_without_javascript_navigation_still_works(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                assert page.query_selector('link[rel="prefetch"]') is None
                page.click(".maatlog-pagination-next")
                page.wait_for_load_state("load")
                assert page.url.endswith(SECOND_PAGE)
        finally:
            browser.close()


@pytest.mark.browser
def test_prefetch_failure_does_not_block_navigation(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.route(
                    f"{base_url}{SECOND_PAGE}",
                    lambda route: route.abort() if route.request.resource_type == "other" else route.continue_(),
                )
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.click(".maatlog-pagination-next")
                page.wait_for_load_state("load")
                assert page.url.endswith(SECOND_PAGE)
                assert page.query_selector(".maatlog-post-card") is not None
        finally:
            browser.close()


@pytest.mark.browser
def test_infinite_scroll_updates_the_prefetch_target(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
                first_next = absolute_href(page, ".maatlog-pagination-next")
                assert first_next is not None
                wait_for_prefetch(page, first_next)

                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_function("() => document.querySelectorAll('.maatlog-post-card').length > 1")
                page.wait_for_function(
                    """(previous) => {
                      const next = document.querySelector('.maatlog-pagination-next');
                      return next instanceof HTMLAnchorElement && next.href !== previous;
                    }""",
                    arg=first_next,
                )
                updated_next = absolute_href(page, ".maatlog-pagination-next")
                assert updated_next is not None
                assert updated_next != first_next
                wait_for_prefetch(page, updated_next)
        finally:
            browser.close()

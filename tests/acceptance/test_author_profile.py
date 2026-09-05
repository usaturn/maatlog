"""Real-browser acceptance checks for the author profile page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

import pytest
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.conftest import AcceptanceSite

ColorScheme = Literal["light", "dark"]

PROFILE_PATH = "blog/author/alice.html"
POST_PATH = "posts/rst-post.html"
FALLBACK_PATH = "blog/author/bob.html"

BOB_ARCHIVE_POST = {
    "posts/bob-note.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: bob-note\n"
        ":maatlog-published-at: 2026-08-05T00:00:00Z\n"
        ":maatlog-tags: python\n"
        ":maatlog-categories: ops\n"
        ":maatlog-authors: bob\n"
        "\n"
        "Bob Note\n"
        "========\n"
        "\n"
        "Fixture post for authors without a profile.\n"
    ),
}

VIEWPORTS = ((1440, 900), (834, 1112), (390, 844))


def _overflow(page: Page) -> int:
    return cast(
        int,
        page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"),
    )


def _element_width(page: Page, selector: str) -> int:
    return cast(
        int,
        page.locator(selector).evaluate("element => Math.round(element.getBoundingClientRect().width)"),
    )


def test_profile_page_embeds_the_about_document(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")

    page = result.html(PROFILE_PATH)

    assert page.select_one(".maatlog-profile[data-maatlog-component='profile']") is not None
    assert "Alice writes about Python" in page
    assert page.select_one(".maatlog-profile-interests") is not None


def test_author_without_a_profile_keeps_the_archive(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default", extra_files=BOB_ARCHIVE_POST)

    page = result.html(FALLBACK_PATH)

    assert page.select_one(".maatlog-archive[data-maatlog-component='archive']") is not None
    assert page.select_one(".maatlog-profile") is None


@pytest.mark.browser
def test_profile_page_never_overflows_horizontally(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(PROFILE_PATH).resolve().as_uri(), wait_until="load")
                    assert _overflow(page) <= 0, f"overflow at {width}x{height}"
                finally:
                    page.close()
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_profile_page_renders_in_both_color_schemes(site: AcceptanceSite, scheme: ColorScheme) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
        try:
            page.goto(result.path(PROFILE_PATH).resolve().as_uri(), wait_until="load")
            assert page.locator(".maatlog-profile-header").is_visible()
            assert page.locator(".maatlog-profile-stats").is_visible()
            assert page.locator(".maatlog-profile-about").is_visible()
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_every_profile_link_is_reachable_by_keyboard(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path(PROFILE_PATH).resolve().as_uri(), wait_until="load")
            expected = set(
                cast(
                    list[str],
                    page.eval_on_selector_all(
                        ".maatlog-profile a[href]", "nodes => nodes.map(node => node.getAttribute('href'))"
                    ),
                )
            )
            reached: set[str] = set()
            for _ in range(300):
                page.keyboard.press("Tab")
                href = page.evaluate(
                    "() => { const el = document.activeElement;"
                    " return el && el.closest('.maatlog-profile') ? el.getAttribute('href') : null; }"
                )
                if isinstance(href, str):
                    reached.add(href)
                if expected <= reached:
                    break
            assert expected <= reached, sorted(expected - reached)
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_profile_main_is_wider_than_a_post_main(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path(POST_PATH).resolve().as_uri(), wait_until="load")
            post_width = _element_width(page, ".maatlog-layout-main")
            page.goto(result.path(PROFILE_PATH).resolve().as_uri(), wait_until="load")
            profile_width = _element_width(page, ".maatlog-layout-main")

            assert profile_width > post_width
        finally:
            page.close()
            browser.close()


def test_post_list_inside_about_document_links_from_the_profile_page(site: AcceptanceSite) -> None:
    """H-1 回帰: About 文書内 post-list のカード URI は埋め込み先（プロフィールページ）基点。"""
    about_rst = "Author About\n============\n\nAlice writes about Python\n\n.. maatlog:post-list::\n   :limit: 1\n"
    result = site.build(
        "html",
        config_overrides={
            "maatlog_author_profiles": {
                "alice": {
                    "avatar": "authors/alice.png",
                    "about_docname": "about",
                },
            },
        },
        extra_files={"about.rst": about_rst},
    )

    # About 文書（about）とプロフィールページ（blog/author/alice）は深さが異なる。
    # H-1 ではカード URI が about.html 基点になり、実在しない blog/author/posts/… を指す。
    assert result.links_are_resolvable(PROFILE_PATH)

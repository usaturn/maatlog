"""Issue #60 アーカイブ絞り込みの受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

ARCHIVE_PAGE = "blog.html"

# SOURCE_DATE_EPOCH (2026-08-15) 以前の投稿のみ公開される。
FIXTURE_POSTS: dict[str, str] = {
    "posts/sphinx-only.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: sphinx-only\n"
        ":maatlog-published-at: 2026-08-01T00:00:00Z\n"
        ":maatlog-tags: sphinx\n"
        ":maatlog-categories: engineering\n"
        ":maatlog-authors: alice\n"
        "\n"
        "Sphinx Only\n"
        "===========\n"
        "\n"
        "Body.\n"
    ),
    "posts/python-ops.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: python-ops\n"
        ":maatlog-published-at: 2026-08-02T00:00:00Z\n"
        ":maatlog-tags: python\n"
        ":maatlog-categories: ops\n"
        ":maatlog-authors: bob\n"
        "\n"
        "Python Ops\n"
        "==========\n"
        "\n"
        "Body.\n"
    ),
    "posts/both-tags.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: both-tags\n"
        ":maatlog-published-at: 2026-08-03T00:00:00Z\n"
        ":maatlog-tags: sphinx, python\n"
        ":maatlog-categories: engineering\n"
        ":maatlog-authors: alice\n"
        "\n"
        "Both Tags\n"
        "=========\n"
        "\n"
        "Body.\n"
    ),
}

EXTRA_CONFIG = {
    "maatlog_tags": {"sphinx": "Sphinx", "python": "Python", "data-analysis": "データ 分析"},
}


def _card_invisible(page: Page, slug: str) -> bool:
    """Return True when the card is not rendered.

    ``card.hidden`` only reports the IDL property. A theme rule such as
    ``.maatlog-post-card { display: flex }`` outranks the UA ``[hidden]``
    rule, so the property can be true while the card still occupies its full
    height. Assert on the rendered box instead.
    """
    return page.evaluate(
        """(slug) => {
            const card = document.querySelector(`.maatlog-post-card[data-slug="${slug}"]`);
            if (card === null) {
              return true;
            }
            return getComputedStyle(card).display === "none" || card.getBoundingClientRect().height === 0;
        }""",
        slug,
    )


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_filter_by_tag_category_author_and_clear(site: AcceptanceSite, theme: str) -> None:
    result = site.build(
        "html",
        theme=theme,
        extra_files=FIXTURE_POSTS,
        config_overrides=EXTRA_CONFIG,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(200)

                assert page.locator('[data-maatlog-component="archive-filter"]').count() == 1
                assert not _card_invisible(page, "sphinx-only")
                assert not _card_invisible(page, "python-ops")
                assert not _card_invisible(page, "both-tags")
                assert not _card_invisible(page, "three-authors")

                page.click('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="python"]')
                assert not _card_invisible(page, "both-tags")
                assert not _card_invisible(page, "python-ops")
                assert _card_invisible(page, "sphinx-only")
                assert _card_invisible(page, "three-authors")

                page.click('[data-maatlog-filter-axis="category"] [data-maatlog-filter-value="engineering"]')
                assert not _card_invisible(page, "both-tags")
                assert _card_invisible(page, "python-ops")
                assert _card_invisible(page, "sphinx-only")
                assert _card_invisible(page, "three-authors")

                page.click('[data-maatlog-filter-axis="author"] [data-maatlog-filter-value="bob"]')
                # Tag=python AND Category=engineering AND Author=bob → all cards hidden
                assert _card_invisible(page, "sphinx-only")
                assert _card_invisible(page, "both-tags")
                assert _card_invisible(page, "python-ops")
                assert _card_invisible(page, "three-authors")
                assert page.locator(".maatlog-archive-empty-filtered:not([hidden])").count() == 1
                assert "No matching posts." in page.locator(".maatlog-archive-empty-filtered").inner_text()

                page.click("[data-maatlog-filter-reset]")
                assert not _card_invisible(page, "sphinx-only")
                assert not _card_invisible(page, "python-ops")
                assert not _card_invisible(page, "both-tags")
                assert not _card_invisible(page, "three-authors")
                assert page.locator(".maatlog-archive-empty-filtered[hidden]").count() == 1
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_same_axis_or_and_japanese_label(site: AcceptanceSite, theme: str) -> None:
    japanese_post = {
        "posts/data-post.rst": (
            ":maatlog-post: true\n"
            ":maatlog-slug: data-post\n"
            ":maatlog-published-at: 2026-08-04T00:00:00Z\n"
            ":maatlog-tags: data-analysis\n"
            ":maatlog-categories: engineering\n"
            ":maatlog-authors: alice\n"
            "\n"
            "Data Post\n"
            "=========\n"
            "\n"
            "Body.\n"
        ),
    }
    result = site.build(
        "html",
        theme=theme,
        extra_files={**FIXTURE_POSTS, **japanese_post},
        config_overrides=EXTRA_CONFIG,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(200)

                chip = page.locator('[data-maatlog-filter-value="data-analysis"]')
                assert chip.inner_text() == "データ 分析"
                chip.click()
                assert not _card_invisible(page, "data-post")
                assert _card_invisible(page, "sphinx-only")
                assert _card_invisible(page, "python-ops")
                assert _card_invisible(page, "both-tags")

                # Same-axis OR: add sphinx → data-post + sphinx-tagged fixture cards
                page.click('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="sphinx"]')
                assert not _card_invisible(page, "data-post")
                assert not _card_invisible(page, "sphinx-only")
                assert not _card_invisible(page, "both-tags")
                assert _card_invisible(page, "python-ops")
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_content_added_reapplies_active_filter(site: AcceptanceSite, theme: str) -> None:
    result = site.build(
        "html",
        theme=theme,
        extra_files=FIXTURE_POSTS,
        config_overrides=EXTRA_CONFIG,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(200)

                page.click('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="sphinx"]')
                page.evaluate(
                    """() => {
                      const archive = document.querySelector('[data-maatlog-component="archive"]');
                      const list = document.querySelector('.maatlog-post-list .maatlog-post-grid')
                        || document.querySelector('.maatlog-post-list');
                      const card = document.createElement('article');
                      card.className = 'maatlog-post-card';
                      card.setAttribute('data-slug', 'appended-other');
                      card.setAttribute('data-maatlog-tags', '["other"]');
                      card.setAttribute('data-maatlog-categories', '[]');
                      card.setAttribute('data-maatlog-authors', '[]');
                      card.innerHTML = '<h2 class="maatlog-post-card-title">Appended</h2>';
                      list.appendChild(card);
                      archive.dispatchEvent(new CustomEvent('maatlog:content-added', {
                        bubbles: true,
                        detail: { cards: [card], url: window.location.href },
                      }));
                    }"""
                )
                assert _card_invisible(page, "appended-other")
                assert not _card_invisible(page, "sphinx-only")
        finally:
            browser.close()


# Carries a tag no other fixture post has, so a filter on ``sphinx`` never matches it.
CURATED_POST: dict[str, str] = {
    "posts/curated-pick.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: curated-pick\n"
        ":maatlog-published-at: 2026-08-05T00:00:00Z\n"
        ":maatlog-tags: curated\n"
        ":maatlog-categories: ops\n"
        ":maatlog-authors: bob\n"
        "\n"
        "Curated Pick\n"
        "============\n"
        "\n"
        "Body.\n"
    ),
}

CURATED_HOME = "# MaatLog Acceptance Blog\n\nIntro.\n\n```{maatlog:post-list}\n:tags: curated\n:limit: 1\n```\n"


def _curated_card_display(page: Page) -> str:
    return page.evaluate(
        """() => {
            const card = document.querySelector('[data-maatlog-component="post-list"] .maatlog-post-card');
            return card === null ? "missing" : getComputedStyle(card).display;
        }"""
    )


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_curated_post_list_survives_archive_filter(site: AcceptanceSite, theme: str) -> None:
    """A ``maatlog:post-list`` in the home body is not archive population.

    ``home.html`` renders the user body inside ``.maatlog-post-list``, so a
    curated list nests under the archive's own list. Curated cards are placed
    with a different intent and must not answer to the archive chips.
    """
    result = site.build(
        "html",
        theme=theme,
        extra_files={**FIXTURE_POSTS, **CURATED_POST, "home.md": CURATED_HOME},
        config_overrides={
            **EXTRA_CONFIG,
            "maatlog_tags": {**EXTRA_CONFIG["maatlog_tags"], "curated": "Curated"},
        },
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}home.html", wait_until="load")
                page.wait_for_timeout(200)

                assert _curated_card_display(page) != "missing"
                assert _curated_card_display(page) != "none"

                # ``curated-pick`` carries no ``sphinx`` tag, so the archive copy hides.
                page.click('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="sphinx"]')
                page.wait_for_timeout(200)

                assert _curated_card_display(page) != "none"
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_visible_curated_post_list_suppresses_empty_message(site: AcceptanceSite, theme: str) -> None:
    """A visible curated card means the page must not announce no matching posts.

    The selected combination hides every archive card, while the nested curated
    list remains outside the archive filter population. The empty state must
    account for that still-visible content.
    """
    result = site.build(
        "html",
        theme=theme,
        extra_files={**FIXTURE_POSTS, **CURATED_POST, "home.md": CURATED_HOME},
        config_overrides={
            **EXTRA_CONFIG,
            "maatlog_tags": {**EXTRA_CONFIG["maatlog_tags"], "curated": "Curated"},
        },
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}home.html", wait_until="load")
                page.wait_for_timeout(200)

                # No archive card has both values, but the curated card does not
                # belong to that archive population and stays visible.
                page.click('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="sphinx"]')
                page.click('[data-maatlog-filter-axis="author"] [data-maatlog-filter-value="bob"]')

                assert _curated_card_display(page) != "none"
                assert page.locator(".maatlog-archive-empty-filtered[hidden]").count() == 1
        finally:
            browser.close()


# ``rare`` rides the newest post, so with page_size 2 it exists on page 1 only.
PAGINATION_POSTS: dict[str, str] = {
    "posts/rare-new.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: rare-new\n"
        ":maatlog-published-at: 2026-08-14T00:00:00Z\n"
        ":maatlog-tags: rare\n"
        ":maatlog-categories: engineering\n"
        ":maatlog-authors: alice\n"
        "\n"
        "Rare New\n"
        "========\n"
        "\n"
        "Body.\n"
    ),
    "posts/common-a.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: common-a\n"
        ":maatlog-published-at: 2026-08-02T00:00:00Z\n"
        ":maatlog-tags: sphinx\n"
        ":maatlog-categories: engineering\n"
        ":maatlog-authors: alice\n"
        "\n"
        "Common A\n"
        "========\n"
        "\n"
        "Body.\n"
    ),
    "posts/common-b.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: common-b\n"
        ":maatlog-published-at: 2026-08-01T00:00:00Z\n"
        ":maatlog-tags: sphinx\n"
        ":maatlog-categories: engineering\n"
        ":maatlog-authors: alice\n"
        "\n"
        "Common B\n"
        "========\n"
        "\n"
        "Body.\n"
    ),
}

PAGINATION_CONFIG: dict[str, object] = {
    "maatlog_page_size": 2,
    "maatlog_tags": {"sphinx": "Sphinx", "python": "Python", "rare": "Rare"},
}


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_chips_are_limited_to_the_population_of_this_page(site: AcceptanceSite, theme: str) -> None:
    """Every rendered chip must have a matching card on this page.

    Chips used to come from the whole site while filtering only ever saw the
    cards of the current page, so a chip whose posts live on page 1 produced a
    permanent "No matching posts." on page 2.
    """
    result = site.build(
        "html",
        theme=theme,
        extra_files=PAGINATION_POSTS,
        config_overrides=PAGINATION_CONFIG,
    )
    assert (result.outdir / "blog/page/2.html").is_file()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}blog/page/2.html", wait_until="load")
                page.wait_for_timeout(200)

                chips = page.evaluate(
                    """() => [...document.querySelectorAll('[data-maatlog-filter-value]')]
                        .map((c) => c.getAttribute('data-maatlog-filter-value'))"""
                )
                assert chips, "page 2 rendered no chips at all"
                assert "rare" not in chips

                for chip in chips:
                    page.click(f'[data-maatlog-filter-value="{chip}"]')
                    page.wait_for_timeout(100)
                    visible = page.evaluate(
                        """() => [...document.querySelectorAll('.maatlog-post-card')]
                            .filter((c) => getComputedStyle(c).display !== 'none').length"""
                    )
                    assert visible > 0, f"chip {chip} matched nothing on this page"
                    assert page.locator(".maatlog-archive-empty-filtered[hidden]").count() == 1
                    page.click("[data-maatlog-filter-reset]")
                    page.wait_for_timeout(100)
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toolbar_is_absent_without_javascript(site: AcceptanceSite, theme: str) -> None:
    """A chip that cannot do anything must not be offered.

    The chips are wired by the theme runtime. Without JavaScript they stay
    inert, so they follow the ``.maatlog-js`` gate the theme toggle uses.
    """
    result = site.build(
        "html",
        theme=theme,
        extra_files=FIXTURE_POSTS,
        config_overrides=EXTRA_CONFIG,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            with serve_directory(result.outdir) as base_url:
                no_js = browser.new_context(java_script_enabled=False)
                page = no_js.new_page()
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                assert page.locator('[data-maatlog-component="archive-filter"]').is_visible() is False
                # The archive itself still works without JavaScript.
                assert page.locator(".maatlog-post-card").count() > 0
                no_js.close()

                with_js = browser.new_context()
                page = with_js.new_page()
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(200)
                assert page.locator('[data-maatlog-component="archive-filter"]').is_visible() is True
                with_js.close()
        finally:
            browser.close()

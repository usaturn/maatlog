"""Issue #63 の受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import Page, Request, Route, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceBuildResult, AcceptanceSite

ARCHIVE_PAGE = "blog.html"
SECOND_PAGE = "blog/page/2.html"


def _tall_excerpt(repeat: int = 16) -> str:
    """A long single-line excerpt so a lone archive card clears the sentinel's rootMargin.

    The archive card only renders ``card.excerpt`` (see ``post-card.html``), never the
    full post body, so padding the body would not change ``blog.html``'s height at all.
    Each page of this fixture (``maatlog_page_size=1``) must independently push the
    infinite-scroll sentinel below ``innerHeight (720) + rootMargin (400) = 1120px`` so
    the sentinel does not already intersect on open — otherwise ``IntersectionObserver``
    fires before the assertions below ever run.
    """
    sentence = "Filler copy that pads this card past the fold so the sentinel starts out of view. "
    return (sentence * repeat).strip()


TALL_EXCERPT = _tall_excerpt()

# 4 本足して公開記事を 6 本にする。page_size=1 なので blog.html + page/2..6 の 6 ページ。
# 既存の 2 記事 (rst-post / md-post) もこのアーカイブの 1, 2 ページ目に乗るため、
# 同じパスへの上書きでタテに長くする（本文ではなく excerpt を伸ばす。上記docstring参照）。
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

# 追加記事は toctree に載らない。ページ生成には影響しないので警告だけ黙らせる。
ARCHIVE_CONFIG: dict[str, object] = {
    "maatlog_page_size": 1,
    "suppress_warnings": ["toc.not_included"],
}


def build_paginated_site(site: AcceptanceSite) -> AcceptanceBuildResult:
    """6 ページのアーカイブを持つ受け入れサイトをビルドする。"""
    return site.build(
        "html",
        theme="maatlog-default",
        config_overrides=ARCHIVE_CONFIG,
        extra_files=EXTRA_POSTS,
    )


def open_archive(page: Page, base_url: str) -> None:
    """アーカイブ 1 ページ目を開き、runtime の初期化完了まで待つ。"""
    page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
    page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")


def slugs(page: Page) -> list[str]:
    """一覧に並んでいるカードの data-slug を文書順で返す。"""
    return page.evaluate("() => [...document.querySelectorAll('.maatlog-post-card')].map((card) => card.dataset.slug)")


def scroll_to_bottom(page: Page) -> None:
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")


THIRD_PAGE = "blog/page/3.html"


def _allow_only_second_page_fetch(page: Page, base_url: str) -> None:
    """Let Infinite Scroll fetch page 2 once, then abort later pages.

    Scrolling to the bottom with ``rootMargin`` still intersecting would otherwise
    autofill through every remaining page before assertions run. Aborting page 3+
    stops the loader after one append so pagination/card href checks stay on the
    post-page-2 DOM (Next → page 3, one appended card).
    """

    def gate(route: Route, request: Request) -> None:
        if request.url.rstrip("/").endswith(f"/{SECOND_PAGE}") or request.url.endswith(SECOND_PAGE):
            route.continue_()
        else:
            route.abort()

    page.route(f"{base_url}blog/page/*", gate)


def _wait_for_second_page(page: Page) -> None:
    scroll_to_bottom(page)
    page.wait_for_function("() => document.querySelectorAll('.maatlog-post-card').length >= 2")
    page.evaluate("() => window.scrollTo(0, 0)")
    # Abort of page 3+ ends the loader; wait until that settles so Next stays page 2's.
    page.wait_for_selector(".maatlog-infinite-sentinel", state="detached")
    assert page.evaluate("() => document.querySelectorAll('.maatlog-post-card').length") == 2


@pytest.mark.browser
def test_appended_pagination_next_link_navigates_to_the_correct_page(site: AcceptanceSite) -> None:
    """After page 2 is appended, pagination Next must target blog/page/3.html."""
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _allow_only_second_page_fetch(page, base_url)
                open_archive(page, base_url)
                _wait_for_second_page(page)

                next_href = page.locator(".maatlog-pagination-next").get_attribute("href")
                assert next_href is not None
                resolved = page.evaluate(
                    "(href) => new URL(href, window.location.href).pathname",
                    next_href,
                )
                assert resolved.endswith(THIRD_PAGE)

                page.unroute(f"{base_url}blog/page/*")
                page.click(".maatlog-pagination-next")
                page.wait_for_load_state("load")

            assert page.url.endswith(THIRD_PAGE)
        finally:
            browser.close()


@pytest.mark.browser
def test_appended_card_title_link_resolves_against_the_current_location(site: AcceptanceSite) -> None:
    """An appended card's post link must resolve and navigate to the post URL."""
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                _allow_only_second_page_fetch(page, base_url)
                open_archive(page, base_url)
                _wait_for_second_page(page)

                link_info = page.evaluate(
                    """() => {
                      const cards = document.querySelectorAll('.maatlog-post-card');
                      const card = cards[cards.length - 1];
                      const link = card.querySelector('.maatlog-post-card-title a');
                      const slug = card.dataset.slug;
                      const href = link.getAttribute('href');
                      const resolved = new URL(href, window.location.href).pathname;
                      return { slug, href, resolved };
                    }"""
                )
                assert link_info["slug"]
                assert link_info["href"]
                assert link_info["resolved"].endswith(f"posts/{link_info['slug']}.html")

                page.click(f'.maatlog-post-card[data-slug="{link_info["slug"]}"] .maatlog-post-card-title a')
                page.wait_for_load_state("load")

            assert page.url.endswith(f"posts/{link_info['slug']}.html")
        finally:
            browser.close()


@pytest.mark.browser
def test_the_next_page_is_appended_near_the_end_of_the_list(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                open_archive(page, base_url)
                before = slugs(page)
                assert len(before) == 1

                scroll_to_bottom(page)
                page.wait_for_function("() => document.querySelectorAll('.maatlog-post-card').length > 1")

                after = slugs(page)

            assert len(after) > len(before)
            assert after[: len(before)] == before
            # 追加は既存の単一グリッドの中。ページごとに grid を生やさない。
            assert page.evaluate("() => document.querySelectorAll('.maatlog-post-grid').length") == 1
        finally:
            browser.close()


@pytest.mark.browser
def test_cards_are_never_appended_twice(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                open_archive(page, base_url)
                for _ in range(8):
                    scroll_to_bottom(page)
                    page.wait_for_timeout(150)
                loaded = slugs(page)

            assert loaded == sorted(set(loaded), key=loaded.index)
            assert len(loaded) == len(set(loaded))
        finally:
            browser.close()


@pytest.mark.browser
def test_loading_stops_on_the_last_page(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                open_archive(page, base_url)
                for _ in range(10):
                    scroll_to_bottom(page)
                    page.wait_for_timeout(150)

                # 6 ページぶんすべてが 1 枚の一覧に並び、sentinel は役目を終えて消える。
                assert len(slugs(page)) == 6
                page.wait_for_selector(".maatlog-infinite-sentinel", state="detached")
                assert page.query_selector(".maatlog-pagination") is not None
        finally:
            browser.close()


@pytest.mark.browser
def test_a_failed_fetch_leaves_the_ordinary_pagination_usable(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                attempts: list[str] = []

                def fail_next_page(route: Route, request: Request) -> None:
                    if request.resource_type not in {"fetch", "xhr"}:
                        route.continue_()
                        return
                    attempts.append(request.url)
                    route.abort()

                page.route(f"{base_url}{SECOND_PAGE}", fail_next_page)
                open_archive(page, base_url)
                for _ in range(6):
                    scroll_to_bottom(page)
                    page.wait_for_timeout(150)

                # 自動読み込みは諦めるが、Next リンクは残っていて実際に遷移できる。
                assert len(slugs(page)) == 1
                assert len(attempts) == 1
                page.wait_for_selector(".maatlog-infinite-sentinel", state="detached")

                page.unroute(f"{base_url}{SECOND_PAGE}")
                page.click(".maatlog-pagination-next")
                page.wait_for_load_state("load")

                assert page.url.endswith(SECOND_PAGE)
                assert len(slugs(page)) >= 1
        finally:
            browser.close()


@pytest.mark.browser
def test_the_same_page_is_never_fetched_twice(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                fetched: list[str] = []

                def record(route: Route, request: Request) -> None:
                    url = request.url
                    # Prefetch (``<link rel="prefetch">``) は別経路。ここでは Infinite Scroll の fetch だけを数える。
                    if url.endswith(".html") and request.resource_type in {"fetch", "xhr"}:
                        fetched.append(url)
                    route.continue_()

                page.route(f"{base_url}blog/page/*", record)
                open_archive(page, base_url)
                for _ in range(10):
                    scroll_to_bottom(page)
                    page.wait_for_timeout(150)

            assert len(fetched) == len(set(fetched))
            assert len(fetched) == 5
        finally:
            browser.close()


# 追加カードへ再適用されることを確かめる probe。#60/#62/#66 はこの機構に載る。
_PROBE_ENHANCER = """
() => {
  window.__events = [];
  document.addEventListener("maatlog:content-added", (event) => {
    window.__events.push(event.detail.cards.length);
  });
  window.maatlog.registerEnhancer("probe", {
    selector: ".maatlog-post-card",
    apply: (card) => {
      card.dataset.probe = "on";
    },
  });
  window.maatlog.enhance(document);
}
"""


@pytest.mark.browser
def test_appended_cards_receive_registered_enhancements(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            with serve_directory(result.outdir) as base_url:
                open_archive(page, base_url)
                page.evaluate(_PROBE_ENHANCER)

                scroll_to_bottom(page)
                page.wait_for_function("() => document.querySelectorAll('.maatlog-post-card').length > 1")
                page.wait_for_timeout(150)

                marked = page.evaluate(
                    "() => [...document.querySelectorAll('.maatlog-post-card')]"
                    ".every((card) => card.dataset.probe === 'on')"
                )
                events = page.evaluate("() => window.__events")

            assert marked is True
            assert events and all(count > 0 for count in events)
        finally:
            browser.close()


@pytest.mark.browser
def test_without_javascript_the_static_pagination_is_the_whole_feature(site: AcceptanceSite) -> None:
    result = build_paginated_site(site)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")

                # JS が作る痕跡はどこにも無い。
                assert page.query_selector(".maatlog-infinite-sentinel") is None
                assert page.query_selector(".maatlog-infinite-status") is None

                page.click(".maatlog-pagination-next")
                page.wait_for_load_state("load")

                assert page.url.endswith(SECOND_PAGE)
                assert page.query_selector(".maatlog-post-card") is not None
        finally:
            browser.close()

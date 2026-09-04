"""Issue #109 の受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

import pytest
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceBuildResult, AcceptanceSite

THEMES = ("maatlog-base", "maatlog-default")

LIST_PAGE = "index.html"
CARD = ".maatlog-post-card"
# index.html の先頭カードは posts/md-post.html を指し、画像・公開日・excerpt・
# category / tag / author を全て備える（tests/acceptance/project/posts/md-post.md）。
POST_URL = "**/posts/md-post.html"
TAG_URL = "**/blog/tag/sphinx.html"


class Hit(TypedDict):
    href: str | None
    cursor: str


def _open(page: Page, result: AcceptanceBuildResult, name: str) -> None:
    page.goto(result.path(name).resolve().as_uri(), wait_until="load")


def _ensure_card_in_view(page: Page) -> None:
    # maatlog-base の index.html では先頭カードが fold 下にあり得る。
    page.locator(CARD).first.scroll_into_view_if_needed()


def _click_centre(page: Page, selector: str) -> None:
    """Overlay に覆われた要素は locator.click では押せないので座標で押す。

    カードが fold 下にあっても対象自身が fold 下にあるとは限らないため、
    スクロールはカードでなく対象の locator に対して行う。
    """
    target = page.locator(selector).first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    assert box is not None, f"not rendered: {selector}"
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


@pytest.mark.browser
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize(
    "selector",
    [
        f"{CARD} .maatlog-post-card-excerpt",
        f"{CARD} .maatlog-post-card-image",
        f"{CARD} .maatlog-post-card-date",
    ],
)
def test_card_body_navigates_to_the_post(site: AcceptanceSite, theme: str, selector: str) -> None:
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _open(page, result, LIST_PAGE)

            _click_centre(page, selector)

            page.wait_for_url(POST_URL)
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", THEMES)
def test_card_padding_navigates_to_the_post(site: AcceptanceSite, theme: str) -> None:
    # 文字も画像も無い余白（meta 行の下）を押しても記事へ行く。
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _open(page, result, LIST_PAGE)
            _ensure_card_in_view(page)
            box = page.locator(CARD).first.bounding_box()
            assert box is not None

            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] - 4)

            page.wait_for_url(POST_URL)
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", THEMES)
def test_taxonomy_links_keep_their_own_destination(site: AcceptanceSite, theme: str) -> None:
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _open(page, result, LIST_PAGE)

            _click_centre(page, f"{CARD} .maatlog-post-card-tags a")

            page.wait_for_url(TAG_URL)
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", THEMES)
def test_card_surface_reads_as_the_post_link(site: AcceptanceSite, theme: str) -> None:
    # hover 表現とクリック可能範囲を一致させる（cursor: pointer を含む）。
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _open(page, result, LIST_PAGE)
            _ensure_card_in_view(page)

            hit = cast(
                Hit,
                page.evaluate(
                    """() => {
                      const card = document.querySelector('.maatlog-post-card');
                      const box = card.querySelector('.maatlog-post-card-excerpt')
                        .getBoundingClientRect();
                      const element = document.elementFromPoint(
                        box.left + box.width / 2,
                        box.top + box.height / 2,
                      );
                      return {
                        href: element.getAttribute('href'),
                        cursor: getComputedStyle(element).cursor,
                      };
                    }"""
                ),
            )

            assert hit["href"] == "posts/md-post.html"
            assert hit["cursor"] == "pointer"
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", THEMES)
def test_card_adds_no_extra_tab_stop(site: AcceptanceSite, theme: str) -> None:
    # overlay は擬似要素なのでタブストップを増やさない。
    result = site.build("html", theme=theme)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            _open(page, result, LIST_PAGE)

            hrefs = cast(
                list[str],
                page.evaluate(
                    """() => [...document.querySelector('.maatlog-post-card')
                        .querySelectorAll('a[href], button, [tabindex]')]
                        .map((element) => element.getAttribute('href') ?? element.tagName)"""
                ),
            )

            assert hrefs == [
                "posts/md-post.html",
                "blog/category/engineering.html",
                "blog/tag/sphinx.html",
                "blog/tag/python.html",
                "blog/author/alice.html",
            ]
        finally:
            browser.close()

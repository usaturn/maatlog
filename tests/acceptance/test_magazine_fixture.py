"""Magazine 専用 fixture がビルドでき、既存コーパスと分離されていることを確認する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.magazine import (
    HOME_PAGE,
    PAGE_SIZE,
    PUBLISHED_SLUGS,
    UNPUBLISHED_SLUGS,
    card_boxes,
    featured_boxes,
    latest_boxes,
)
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite


def test_magazine_fixture_builds_a_dedicated_home(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")

    assert result.succeeded
    assert result.exists("home.html")
    assert result.exists("blog.html")
    assert result.exists("index.html")


def test_magazine_fixture_publishes_exactly_the_expected_corpus(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    index = result.domain().data["index"]
    assert index is not None
    published = tuple(post.slug for post in index.published)

    assert published == PUBLISHED_SLUGS
    for slug in UNPUBLISHED_SLUGS:
        assert slug not in published


def test_magazine_home_shows_featured_and_latest_without_duplication(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    home = result.html(HOME_PAGE)
    slugs = [card["data-slug"] for card in home.select(".maatlog-post-card")]

    # Featured 3 + Latest 9 = 公開 12 本ちょうど。重複しない。
    assert len(slugs) == 3 + PAGE_SIZE
    assert len(set(slugs)) == len(slugs)
    assert set(slugs) == set(PUBLISHED_SLUGS)


def test_magazine_home_marks_featured_and_latest_variants(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    home = result.html(HOME_PAGE)
    variants = [card.get("data-maatlog-card-variant", "") for card in home.select(".maatlog-post-card")]

    assert variants[:3] == ["lead", "secondary", "secondary"]
    assert variants[3:] == ["latest"] * PAGE_SIZE


def test_magazine_home_uses_the_latest_articles_heading(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    text = result.text(HOME_PAGE)

    # NOTE: HtmlPage.select_one は開始タグの属性 dict だけを返すため、見出しの
    # テキスト自体はビルド済み HTML 文字列で検証する（Plan の意図は同一）。
    assert result.html(HOME_PAGE).select_one(".maatlog-post-list-heading") is not None
    assert '<h2 class="maatlog-post-list-heading">Latest articles</h2>' in text
    assert "Older posts" not in text


@pytest.mark.browser
def test_card_boxes_read_theme_api_variants(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
            boxes = card_boxes(page)
            featured = featured_boxes(boxes)
            latest = latest_boxes(boxes)

            assert [box["variant"] for box in featured] == ["lead", "secondary", "secondary"]
            assert [box["variant"] for box in latest] == ["latest"] * PAGE_SIZE
            assert [box["slug"] for box in featured + latest] == list(PUBLISHED_SLUGS)
        finally:
            browser.close()

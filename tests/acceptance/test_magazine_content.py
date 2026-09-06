"""Featured 選択シナリオと境界コンテンツを検証する（Issue #181）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.magazine import (
    HOME_PAGE,
    PAGE_SIZE,
    PUBLISHED_SLUGS,
    card_boxes,
    featured_boxes,
    horizontal_overflow,
)
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite


def _home_slugs(site: AcceptanceSite, overrides: dict[str, object] | None = None) -> list[str]:
    result = site.build("html", theme="maatlog-default", config_overrides=overrides)
    return [card["data-slug"] for card in result.html(HOME_PAGE).select(".maatlog-post-card")]


def test_default_selection_uses_the_three_newest_posts(magazine_site: AcceptanceSite) -> None:
    slugs = _home_slugs(magazine_site)
    assert slugs[:3] == list(PUBLISHED_SLUGS[:3])
    assert slugs[3:] == list(PUBLISHED_SLUGS[3:])
    assert len(slugs) == 3 + PAGE_SIZE


def test_empty_selection_matches_the_default(magazine_site: AcceptanceSite) -> None:
    assert _home_slugs(magazine_site, {"maatlog_featured_posts": ()}) == _home_slugs(magazine_site)


def test_explicit_three_slugs_keep_their_order_and_leave_latest_disjoint(magazine_site: AcceptanceSite) -> None:
    pinned = ("mag-oldest", "mag-second-noimage", "mag-lead-en")
    slugs = _home_slugs(magazine_site, {"maatlog_featured_posts": pinned})

    assert slugs[:3] == list(pinned)
    assert set(slugs[3:]).isdisjoint(pinned)
    assert len(slugs) == len(set(slugs))
    assert set(slugs) == set(PUBLISHED_SLUGS)


def test_single_pinned_slug_is_backfilled_without_duplication(magazine_site: AcceptanceSite) -> None:
    slugs = _home_slugs(magazine_site, {"maatlog_featured_posts": ("mag-oldest",)})

    assert slugs[0] == "mag-oldest"
    assert slugs[:3] == ["mag-oldest", "mag-lead-en", "mag-second-ja"]
    assert set(slugs[3:]).isdisjoint(slugs[:3])
    assert len(set(slugs[:3])) == 3


def test_fourth_pinned_slug_stays_in_latest(magazine_site: AcceptanceSite) -> None:
    pinned = ("mag-oldest", "mag-second-noimage", "mag-lead-en", "mag-11")
    slugs = _home_slugs(magazine_site, {"maatlog_featured_posts": pinned})

    assert slugs[:3] == list(pinned[:3])
    assert "mag-11" in slugs[3:]


@pytest.mark.parametrize("page_size", [1, 2, 3])
def test_small_page_sizes_keep_featured_at_three(magazine_site: AcceptanceSite, page_size: int) -> None:
    slugs = _home_slugs(magazine_site, {"maatlog_page_size": page_size})

    assert slugs[:3] == list(PUBLISHED_SLUGS[:3])
    assert len(slugs) == 3 + page_size
    assert len(set(slugs)) == len(slugs)


_ALL_POSTS = tuple(f"posts/{slug}.rst" for slug in PUBLISHED_SLUGS)


def _exclude_all_but(count: int) -> dict[str, object]:
    keep = set(_ALL_POSTS[:count])
    return {"exclude_patterns": ["**/__pycache__", *[name for name in _ALL_POSTS if name not in keep]]}


@pytest.mark.browser
@pytest.mark.parametrize("published", [0, 1, 2])
def test_small_corpora_render_without_gaps_or_overflow(magazine_site: AcceptanceSite, published: int) -> None:
    result = magazine_site.build("html", theme="maatlog-default", config_overrides=_exclude_all_but(published))
    assert result.exists(HOME_PAGE)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((1920, 1080), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
                    boxes = card_boxes(page)
                    assert len(boxes) == published, f"{published}@{width}"
                    assert len(featured_boxes(boxes)) == min(published, 3)
                    assert horizontal_overflow(page) == 0, f"{published}@{width}"
                    heading = page.locator(".maatlog-post-list-heading")
                    if published <= 3:
                        assert heading.count() == 0
                finally:
                    page.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_cards_without_images_or_excerpts_render_cleanly(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")

            assert page.locator("[data-slug='mag-second-noimage'] .maatlog-post-card-image").count() == 0
            assert page.locator("[data-slug='mag-long-ja-title'] .maatlog-post-card-image").count() == 0
            assert page.locator("[data-slug='mag-noexcerpt'] .maatlog-post-card-excerpt").count() == 0
            alts = page.locator(".maatlog-post-card-image").evaluate_all(
                "(nodes) => nodes.map((node) => node.getAttribute('alt'))"
            )
            assert alts and all(alt == "" for alt in alts)
        finally:
            browser.close()


@pytest.mark.browser
def test_long_titles_do_not_overflow_their_cards(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((1920, 1080), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
                    assert horizontal_overflow(page) == 0, width
                    overflowed = page.evaluate(
                        """
                        () => Array.from(document.querySelectorAll('.maatlog-post-card'))
                          .filter((card) => card.scrollWidth - card.clientWidth > 1)
                          .map((card) => card.dataset.slug ?? '')
                        """
                    )
                    assert overflowed == [], f"{width}: {overflowed}"
                finally:
                    page.close()
        finally:
            browser.close()

"""Magazine Home のレイアウトを実ブラウザの座標で検証する（Issue #181）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.magazine import (
    ARCHIVE_PAGE,
    HOME_PAGE,
    LATEST_COLUMNS_EXACT,
    LATEST_COLUMNS_MIN,
    VIEWPORTS,
    card_boxes,
    featured_boxes,
    featured_is_one_plus_two,
    featured_is_stacked,
    horizontal_overflow,
    latest_boxes,
    row_widths,
)
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

REGRESSION_PAGES = (HOME_PAGE, ARCHIVE_PAGE, "index.html", "posts/mag-lead-en.html")


@pytest.mark.browser
def test_magazine_pages_never_scroll_horizontally(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    for relative in REGRESSION_PAGES:
                        page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                        assert horizontal_overflow(page) == 0, f"{relative}@{width}"
                finally:
                    page.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_magazine_home_renders_every_published_card_in_the_viewport(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
                    boxes = card_boxes(page)
                    assert len(boxes) == 12, f"{width}: {len(boxes)} cards"
                    for box in boxes:
                        assert box["width"] > 0 and box["height"] > 0, f"{box['slug']}@{width}"
                        assert box["left"] >= 0, f"{box['slug']}@{width}"
                        assert box["left"] + box["width"] <= width + 1, f"{box['slug']}@{width}"
                finally:
                    page.close()
        finally:
            browser.close()


WIDE_VIEWPORTS = (3840, 2560, 1920, 1280)


@pytest.mark.browser
def test_featured_uses_the_contracted_arrangement_at_every_viewport(
    magazine_site: AcceptanceSite,
) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
                    featured = featured_boxes(card_boxes(page))
                    assert len(featured) == 3, f"{width}: {len(featured)} featured cards"
                    if width in WIDE_VIEWPORTS:
                        assert featured_is_one_plus_two(featured), (
                            f"{width}: {[(b['slug'], b['top'], b['left'], b['width'], b['height']) for b in featured]}"
                        )
                    else:
                        assert featured_is_stacked(featured), (
                            f"{width}: {[(b['slug'], b['top'], b['left']) for b in featured]}"
                        )
                finally:
                    page.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_latest_grid_uses_the_contracted_column_count(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
                    rows = row_widths(latest_boxes(card_boxes(page)))
                    assert rows, f"{width}: no latest cards"
                    observed = max(rows)
                    if width in LATEST_COLUMNS_EXACT:
                        assert observed == LATEST_COLUMNS_EXACT[width], f"{width}: rows={rows}"
                    else:
                        assert observed >= LATEST_COLUMNS_MIN[width], f"{width}: rows={rows}"
                    assert horizontal_overflow(page) == 0, f"{width}"
                finally:
                    page.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_lead_is_visually_stronger_than_secondary_and_latest(magazine_site: AcceptanceSite) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
            boxes = card_boxes(page)
            featured = featured_boxes(boxes)
            latest = latest_boxes(boxes)
            lead, secondary = featured[0], featured[1]
            first_latest = latest[0]

            assert lead["width"] * lead["height"] > secondary["width"] * secondary["height"]
            assert secondary["width"] * secondary["height"] > first_latest["width"] * first_latest["height"]
            assert lead["font_size"] >= secondary["font_size"] >= first_latest["font_size"]
        finally:
            browser.close()


@pytest.mark.browser
def test_dom_order_matches_the_visual_order_of_featured_cards(
    magazine_site: AcceptanceSite,
) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path(HOME_PAGE).resolve().as_uri(), wait_until="load")
                    featured = featured_boxes(card_boxes(page))
                    visual = sorted(featured, key=lambda box: (box["top"], box["left"]))
                    assert [box["slug"] for box in featured] == [box["slug"] for box in visual], f"{width}"
                finally:
                    page.close()
        finally:
            browser.close()

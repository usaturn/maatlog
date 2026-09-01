from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

import pytest
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

WIDE_VIEWPORTS = ((1280, 720), (1920, 1080), (2560, 1440))
REPRESENTATIVE_PAGES = (
    "index.html",
    "guide.html",
    "blog.html",
    "posts/rst-post.html",
)
# body margin (~8px) + layout padding (1rem). Must stay padding-sized as
# viewport grows; the old 1fr rails produced 300px+ gutters at 1920.
MAX_OUTER_GUTTER_PX = 64


class LayoutMetrics(TypedDict):
    overflow: int
    viewport_width: int
    nav_left: int
    main_width: int
    content_right: int


def _layout_metrics(page: Page) -> LayoutMetrics:
    return cast(
        LayoutMetrics,
        page.evaluate(
            """() => {
              const box = (selector) => {
                const element = document.querySelector(selector);
                if (!element) return null;
                return element.getBoundingClientRect();
              };
              const nav = box('.maatlog-nav');
              const main = box('.maatlog-layout-main');
              const toc = box('.maatlog-toc');
              const rightEdge = toc ? toc.right : main.right;
              return {
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
                viewport_width: document.documentElement.clientWidth,
                nav_left: Math.round(nav ? nav.left : main.left),
                main_width: Math.round(main.width),
                content_right: Math.round(rightEdge),
              };
            }"""
        ),
    )


def _element_width(page: Page, selector: str) -> int:
    return cast(
        int,
        page.locator(selector).evaluate("element => Math.round(element.getBoundingClientRect().width)"),
    )


def _assert_outer_gutters_stay_padding_sized(metrics: LayoutMetrics, relative: str) -> None:
    right_gutter = metrics["viewport_width"] - metrics["content_right"]
    assert metrics["overflow"] == 0, relative
    assert metrics["nav_left"] <= MAX_OUTER_GUTTER_PX, f"{relative}: left gutter {metrics['nav_left']}px"
    assert right_gutter <= MAX_OUTER_GUTTER_PX, f"{relative}: right gutter {right_gutter}px"


@pytest.mark.browser
def test_wide_shell_fills_the_viewport_instead_of_growing_side_rails(
    site: AcceptanceSite,
) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            widths_by_page: dict[str, list[int]] = {relative: [] for relative in REPRESENTATIVE_PAGES}
            for width, height in WIDE_VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    for relative in REPRESENTATIVE_PAGES:
                        page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                        metrics = _layout_metrics(page)
                        _assert_outer_gutters_stay_padding_sized(metrics, f"{relative}@{width}")
                        assert metrics["main_width"] > 600, relative
                        widths_by_page[relative].append(metrics["main_width"])
                finally:
                    page.close()

            for relative, widths in widths_by_page.items():
                assert widths[1] > widths[0], relative
                assert widths[2] > widths[1], relative
        finally:
            browser.close()


@pytest.mark.browser
def test_wide_content_fills_the_main_column(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path("index.html").resolve().as_uri(), wait_until="load")
            main_width = _element_width(page, ".maatlog-layout-main")
            list_width = _element_width(page, ".maatlog-post-list")
            assert abs(list_width - main_width) <= 2

            page.goto(result.path("guide.html").resolve().as_uri(), wait_until="load")
            guide_body = _element_width(page, ".body")
            assert abs(guide_body - _element_width(page, ".maatlog-layout-main")) <= 2
            assert abs(_element_width(page, ".body > section > h1") - guide_body) <= 2

            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            archive_width = _element_width(page, ".maatlog-archive")
            assert abs(archive_width - _element_width(page, ".maatlog-layout-main")) <= 2
            assert abs(_element_width(page, ".maatlog-archive .maatlog-post-list") - (archive_width - 32)) <= 2

            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            post_width = _element_width(page, ".maatlog-post")
            assert abs(post_width - _element_width(page, ".maatlog-layout-main")) <= 2
            assert abs(_element_width(page, ".maatlog-post-body") - (post_width - 32)) <= 2
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(1024, 768), (768, 1024)])
def test_responsive_pages_have_no_horizontal_overflow(site: AcceptanceSite, width: int, height: int) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for relative in REPRESENTATIVE_PAGES:
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                metrics = _layout_metrics(page)
                assert metrics["overflow"] == 0, relative
                assert metrics["main_width"] <= width, relative

            page.goto(result.path("index.html").resolve().as_uri(), wait_until="load")
            assert _element_width(page, ".maatlog-post-list") <= _element_width(page, ".body")
        finally:
            page.close()
            browser.close()

"""Layout shell contract: main cap, centering, rail-aware width (Issue #204)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from acceptance.width_contract import (
    CONTRACT_VIEWPORTS,
    EDGE_TOLERANCE_PX,
    OVERFLOW_TOLERANCE_PX,
    document_overflow,
    measure_edges,
)
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.conftest import AcceptanceSite, ProjectFactory
    from playwright.sync_api import Page

NO_RAIL_FILES = {"about.rst": "About\n=====\n\nA plain page that is not a post.\n"}
NO_RAIL_CONFIG: dict[str, object] = {"maatlog_default_author": None}


def _shell_metrics(page: Page) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        page.evaluate(
            """() => {
              const box = (selector) => {
                const element = document.querySelector(selector);
                return element ? element.getBoundingClientRect() : null;
              };
              const layout = box('.maatlog-layout');
              const nav = box('.maatlog-nav');
              const main = box('.maatlog-layout-main');
              const rail = box('.maatlog-right-rail');
              const mainEl = document.querySelector('.maatlog-layout-main');
              const layoutEl = document.querySelector('.maatlog-layout');
              const cap = mainEl ? parseFloat(getComputedStyle(mainEl).maxWidth) : NaN;
              const gap = layoutEl ? parseFloat(getComputedStyle(layoutEl).columnGap
                || getComputedStyle(layoutEl).gap) : NaN;
              const hasRail = Boolean(
                document.querySelector('.maatlog-layout-has-rail')
              );
              return {
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
                viewport: document.documentElement.clientWidth,
                hasRail,
                layoutLeft: layout ? Math.round(layout.left) : null,
                layoutRight: layout ? Math.round(layout.right) : null,
                layoutWidth: layout ? Math.round(layout.width) : null,
                navRight: nav ? Math.round(nav.right) : null,
                navWidth: nav ? Math.round(nav.width) : null,
                mainLeft: main ? Math.round(main.left) : null,
                mainRight: main ? Math.round(main.right) : null,
                mainWidth: main ? Math.round(main.width) : null,
                railLeft: rail ? Math.round(rail.left) : null,
                railWidth: rail ? Math.round(rail.width) : null,
                mainCap: Number.isFinite(cap) ? Math.round(cap) : null,
                gap: Number.isFinite(gap) ? Math.round(gap) : null,
              };
            }"""
        ),
    )


@pytest.mark.browser
@pytest.mark.parametrize("width,height", ((1920, 1080), (2560, 1440), (3840, 2160)))
def test_wide_shell_with_rail_is_centered_after_main_caps(site: AcceptanceSite, width: int, height: int) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            assert metrics["hasRail"] is True, metrics
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
            left = metrics["layoutLeft"]
            right = metrics["viewport"] - metrics["layoutRight"]
            assert abs(left - right) <= EDGE_TOLERANCE_PX, metrics
            assert metrics["mainWidth"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, metrics
            assert left > 16, metrics  # padding-sized gutter より大きい外側余白
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_wide_shell_without_rail_omits_rail_track(make_project: ProjectFactory) -> None:
    result = make_project(files=NO_RAIL_FILES, theme="maatlog-default", config=NO_RAIL_CONFIG).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path("about.html").resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            assert metrics["hasRail"] is False, metrics
            assert metrics["railLeft"] is None, metrics
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
            # 2 列 shell は 3 列より狭い（rail+gap を足していない）。
            with_rail_min = (
                (metrics["navWidth"] or 0)
                + (metrics["gap"] or 0)
                + (metrics["mainCap"] or 0)
                + (metrics["gap"] or 0)
                + 100
            )
            assert metrics["layoutWidth"] < with_rail_min, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_gaps_match_space_lg_between_tracks(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            nav_main = metrics["mainLeft"] - metrics["navRight"]
            main_rail = metrics["railLeft"] - metrics["mainRight"]
            assert abs(nav_main - metrics["gap"]) <= EDGE_TOLERANCE_PX, metrics
            assert abs(main_rail - metrics["gap"]) <= EDGE_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), CONTRACT_VIEWPORTS)
def test_contract_viewports_do_not_overflow(site: AcceptanceSite, width: int, height: int) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for relative in ("index.html", "guide.html", "blog.html", "posts/rst-post.html"):
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX, relative
                main = measure_edges(page, ".maatlog-layout-main")
                assert main is not None
                assert main["width"] <= width
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_medium_and_mobile_order_unchanged(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 768, "height": 1024})
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            order = page.evaluate(
                """() => {
                  const toc = document.querySelector('.maatlog-toc');
                  const main = document.querySelector('.maatlog-layout-main');
                  const nav = document.querySelector('.maatlog-nav');
                  return {
                    tocTop: toc ? toc.getBoundingClientRect().top : null,
                    mainTop: main.getBoundingClientRect().top,
                    navTop: nav.getBoundingClientRect().top,
                    overflow: document.documentElement.scrollWidth
                      - document.documentElement.clientWidth,
                  };
                }"""
            )
            assert order["overflow"] <= OVERFLOW_TOLERANCE_PX, order
            if order["tocTop"] is not None:
                assert order["tocTop"] < order["mainTop"] < order["navTop"], order
            page.close()

            page = browser.new_page(viewport={"width": 1024, "height": 1366})
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            medium = page.evaluate(
                """() => {
                  const rail = document.querySelector('.maatlog-right-rail');
                  const main = document.querySelector('.maatlog-layout-main');
                  return {
                    railTop: rail ? rail.getBoundingClientRect().top : null,
                    mainTop: main.getBoundingClientRect().top,
                    areas: getComputedStyle(document.querySelector('.maatlog-layout'))
                      .gridTemplateAreas,
                  };
                }"""
            )
            if medium["railTop"] is not None:
                assert medium["railTop"] < medium["mainTop"], medium
            page.close()

            page = browser.new_page(viewport={"width": 1025, "height": 1366})
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            wide = _shell_metrics(page)
            assert wide["hasRail"] is True
            if wide["railLeft"] is not None:
                assert wide["railLeft"] > wide["mainRight"] - 8, wide
            page.close()
        finally:
            browser.close()


@pytest.mark.browser
def test_wide_components_stay_within_capped_main(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            checks = (
                ("index.html", ".maatlog-post-grid, .maatlog-post-list, .body"),
                ("blog.html", ".maatlog-archive"),
                ("posts/rst-post.html", ".maatlog-post"),
                ("guide.html", ".body"),
            )
            for relative, selector in checks:
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                main = measure_edges(page, ".maatlog-layout-main")
                target = measure_edges(page, selector)
                assert main is not None and target is not None, relative
                assert target["width"] <= main["width"] + EDGE_TOLERANCE_PX, relative
                assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX, relative
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_shell_cap_works_without_javascript(site: AcceptanceSite) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, java_script_enabled=False)
        page = context.new_page()
        try:
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
            assert metrics["mainCap"] is not None, metrics
            assert metrics["mainWidth"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, metrics
        finally:
            page.close()
            context.close()
            browser.close()


@pytest.mark.browser
def test_magazine_home_does_not_overflow_when_main_caps(
    magazine_site: AcceptanceSite,
) -> None:
    result = magazine_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width, height in ((1920, 1080), (3840, 2160)):
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path("index.html").resolve().as_uri(), wait_until="load")
                    assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX, width
                    main = measure_edges(page, ".maatlog-layout-main")
                    assert main is not None
                    cap = page.evaluate(
                        "() => parseFloat(getComputedStyle(document.querySelector('.maatlog-layout-main')).maxWidth)"
                    )
                    assert main["width"] <= round(cap) + EDGE_TOLERANCE_PX
                finally:
                    page.close()
        finally:
            browser.close()

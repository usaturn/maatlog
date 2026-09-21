"""Issue #203: default テーマの content-width 揃え（読み取り専用 width_contract fixture）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest
from acceptance.built_sites import BuiltSite
from acceptance.width_contract import (
    CODE_OUTER_CAPTIONED,
    CODE_OUTER_PLAIN,
    EDGE_TOLERANCE_PX,
    OVERFLOW_TOLERANCE_PX,
    REFERENCE_BOX_NORMAL,
    REFERENCE_BOX_POST,
    WRAPPER_SELECTOR,
    document_overflow,
    measure_edges,
    measure_reference_box,
)
from playwright.sync_api import Error

if TYPE_CHECKING:
    from acceptance.width_contract import ElementEdges
    from playwright.sync_api import Browser, BrowserContext, Page

POST_PAGE = "posts/width-post.html"
NORMAL_PAGE = "normal.html"
TABLES_PAGE = "tables.html"
CODE_PAGE = "code.html"
PROSE_PAGE = "prose.html"

BuiltWidthContractSite = Callable[..., BuiltSite]


def _aligned(left: ElementEdges, right: ElementEdges) -> None:
    assert abs(left["left"] - right["left"]) <= EDGE_TOLERANCE_PX, (left, right)
    assert abs(left["right"] - right["right"]) <= EDGE_TOLERANCE_PX, (left, right)


def _inside(box: ElementEdges, reference: ElementEdges) -> None:
    assert box["left"] >= reference["left"] - EDGE_TOLERANCE_PX, (box, reference)
    assert box["right"] <= reference["right"] + EDGE_TOLERANCE_PX, (box, reference)


def _open(
    browser: Browser,
    built: BuiltSite,
    page_name: str,
    *,
    width: int,
    height: int,
    js: bool = True,
) -> tuple[BrowserContext, Page]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        java_script_enabled=js,
    )
    try:
        page = context.new_page()
        page.goto((built.outdir / page_name).resolve().as_uri(), wait_until="load")
    except Exception:
        context.close()
        raise
    return context, page


def _close(context: BrowserContext, page: Page) -> None:
    page.close()
    context.close()


@pytest.mark.browser
def test_open_closes_context_when_navigation_fails(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    contexts_before = shared_browser.contexts

    with pytest.raises(Error, match="ERR_FILE_NOT_FOUND"):
        _open(shared_browser, built, "missing.html", width=1280, height=720)

    assert shared_browser.contexts == contexts_before


@pytest.mark.browser
def test_post_targets_share_one_reading_width(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    context, page = _open(shared_browser, built, POST_PAGE, width=1280, height=720)
    try:
        reference = measure_reference_box(page, REFERENCE_BOX_POST)
        prose = measure_edges(page, f"{REFERENCE_BOX_POST} section > p")
        heading = measure_edges(page, f"{REFERENCE_BOX_POST} section > h2")
        wrapper = measure_edges(page, f"{REFERENCE_BOX_POST} {WRAPPER_SELECTOR}")
        code = measure_edges(page, f"{REFERENCE_BOX_POST} {CODE_OUTER_PLAIN}")
        main = measure_edges(page, ".maatlog-layout-main")
        assert reference and prose and heading and wrapper and code and main
        _aligned(prose, heading)
        _aligned(prose, wrapper)
        _aligned(prose, code)
        _inside(prose, reference)
        _inside(prose, main)
        assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX
    finally:
        _close(context, page)


@pytest.mark.browser
def test_normal_page_headings_match_prose(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    context, page = _open(shared_browser, built, NORMAL_PAGE, width=1920, height=1080)
    try:
        prose = measure_edges(page, f"{REFERENCE_BOX_NORMAL} section > p")
        heading = measure_edges(page, f"{REFERENCE_BOX_NORMAL} section > h2")
        assert prose and heading
        _aligned(prose, heading)
    finally:
        _close(context, page)


@pytest.mark.browser
def test_percent_width_does_not_reshrink_nested_lists(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site(
        config_overrides={"maatlog_content_width": "90%"},
    )
    page = shared_browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        page.goto((built.outdir / PROSE_PAGE).resolve().as_uri(), wait_until="load")
        reference = measure_reference_box(page, REFERENCE_BOX_NORMAL)
        prose = measure_edges(page, f"{REFERENCE_BOX_NORMAL} section > p")
        widths = page.evaluate(
            """() => {
              const outer = document.querySelector(
                '.maatlog-layout-page-normal .body section > ul'
              );
              const inner = outer ? outer.querySelector('ul') : null;
              const quote = document.querySelector(
                '.maatlog-layout-page-normal .body section > blockquote'
              );
              const quoteP = quote ? quote.querySelector('p') : null;
              const quoteCS = quote ? getComputedStyle(quote) : null;
              return {
                outer: outer ? Math.round(outer.getBoundingClientRect().width) : null,
                inner: inner ? Math.round(inner.getBoundingClientRect().width) : null,
                quoteP: quoteP ? Math.round(quoteP.getBoundingClientRect().width) : null,
                // テーマの blockquote は両側 padding + 左罫線を持つため、
                // 内側 p は content 幅いっぱい（% 再適用なし）であることを見る。
                quoteContent: quote
                  ? Math.round(
                      quote.clientWidth -
                        parseFloat(quoteCS.paddingLeft) -
                        parseFloat(quoteCS.paddingRight)
                    )
                  : null,
              };
            }"""
        )
        assert reference and prose
        expected = round(reference["width"] * 0.9)
        assert abs(prose["width"] - expected) <= EDGE_TOLERANCE_PX, (prose, expected)
        assert widths["outer"] is not None and widths["inner"] is not None
        assert abs(widths["outer"] - prose["width"]) <= EDGE_TOLERANCE_PX
        assert widths["inner"] > round(widths["outer"] * 0.9) + EDGE_TOLERANCE_PX
        assert widths["quoteP"] is not None
        assert widths["quoteContent"] is not None
        assert abs(widths["quoteP"] - widths["quoteContent"]) <= EDGE_TOLERANCE_PX
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("value", ["90%", "100%"])
@pytest.mark.parametrize(("width", "height"), [(390, 844), (3840, 2160)])
def test_percent_settings_stay_inside_the_reference_box(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
    value: str,
    width: int,
    height: int,
) -> None:
    built = built_width_contract_site(
        config_overrides={"maatlog_content_width": value},
    )
    page = shared_browser.new_page(viewport={"width": width, "height": height})
    try:
        page.goto((built.outdir / POST_PAGE).resolve().as_uri(), wait_until="load")
        reference = measure_reference_box(page, REFERENCE_BOX_POST)
        prose = measure_edges(page, f"{REFERENCE_BOX_POST} section > p")
        assert reference and prose
        _inside(prose, reference)
        if value == "100%":
            assert abs(prose["right"] - reference["right"]) <= EDGE_TOLERANCE_PX
        assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX
    finally:
        page.close()


@pytest.mark.browser
def test_fixed_and_clamp_widths_do_not_escape_the_reference_box(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    cases = (
        ("72rem", 1920, 1080),
        ("clamp(42rem, 70vw, 90rem)", 1280, 720),
        ("clamp(42rem, 70vw, 90rem)", 2560, 1440),
    )
    for value, width, height in cases:
        built = built_width_contract_site(
            config_overrides={"maatlog_content_width": value},
        )
        page = shared_browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto((built.outdir / POST_PAGE).resolve().as_uri(), wait_until="load")
            reference = measure_reference_box(page, REFERENCE_BOX_POST)
            prose = measure_edges(page, f"{REFERENCE_BOX_POST} section > p")
            assert reference and prose
            _inside(prose, reference)
            assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX
        finally:
            page.close()


@pytest.mark.browser
def test_short_table_rules_reach_the_right_edge(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    context, page = _open(shared_browser, built, TABLES_PAGE, width=1280, height=720)
    try:
        metrics = page.evaluate(
            """() => {
              const table = document.querySelector(
                '.maatlog-layout-page-normal .body section > .maatlog-table-wrapper table.docutils'
              );
              if (!table) return null;
              const last = table.querySelector('thead th:last-child, tbody tr td:last-child');
              const tableBox = table.getBoundingClientRect();
              const cellBox = last.getBoundingClientRect();
              return {
                tableRight: Math.round(tableBox.right),
                cellRight: Math.round(cellBox.right),
                tableWidth: Math.round(tableBox.width),
                wrapperWidth: Math.round(table.parentElement.getBoundingClientRect().width),
              };
            }"""
        )
        assert metrics is not None
        assert abs(metrics["cellRight"] - metrics["tableRight"]) <= EDGE_TOLERANCE_PX, metrics
        assert abs(metrics["tableWidth"] - metrics["wrapperWidth"]) <= EDGE_TOLERANCE_PX, metrics
    finally:
        _close(context, page)


@pytest.mark.browser
def test_wide_table_scrolls_inside_the_wrapper(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    context, page = _open(shared_browser, built, TABLES_PAGE, width=390, height=844, js=False)
    try:
        metrics = page.evaluate(
            """() => {
              const wrappers = [...document.querySelectorAll('.maatlog-table-wrapper')];
              const wide = wrappers.find((node) => node.scrollWidth > node.clientWidth + 1);
              return {
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
                found: wide != null,
                wrapperExists: wrappers.length > 0,
              };
            }"""
        )
        assert metrics["wrapperExists"] is True
        assert metrics["found"] is True, metrics
        assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
    finally:
        _close(context, page)


@pytest.mark.browser
def test_singlehtml_wide_table_scrolls_without_widening_the_page(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    # singlehtml は wrapper を出さない（Theme API 1.19）。裸の table.docutils が
    # 自己スクロールし、document を横に広げないこと。
    built = built_width_contract_site(
        "singlehtml",
        warningiserror=False,
    )
    context = shared_browser.new_context(
        viewport={"width": 390, "height": 844},
        java_script_enabled=False,
    )
    try:
        page = context.new_page()
        page.goto((built.outdir / "index.html").resolve().as_uri(), wait_until="load")
        metrics = page.evaluate(
            """() => {
              const wrappers = [...document.querySelectorAll('.maatlog-table-wrapper')];
              const tables = [...document.querySelectorAll('table.docutils')];
              const wide = tables.find((node) => node.scrollWidth > node.clientWidth + 1);
              return {
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
                wrapperCount: wrappers.length,
                tableCount: tables.length,
                tableScrolls: wide != null,
              };
            }"""
        )
        assert metrics["tableCount"] > 0, metrics
        assert metrics["wrapperCount"] == 0, metrics
        assert metrics["tableScrolls"] is True, metrics
        assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
    finally:
        context.close()


@pytest.mark.browser
def test_long_code_scrolls_inside_the_outer_box(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    context, page = _open(shared_browser, built, CODE_PAGE, width=1280, height=720)
    try:
        prose = measure_edges(page, f"{REFERENCE_BOX_NORMAL} section > p")
        captioned = measure_edges(page, CODE_OUTER_CAPTIONED)
        plain = measure_edges(page, CODE_OUTER_PLAIN)
        # 内側スクロール実体は pre（linenos は span 形式。Contingency による等価修正）。
        inner = page.evaluate(
            """() => {
              const pres = [
                ...document.querySelectorAll(
                  '.literal-block-wrapper pre, div[class*="highlight-"] pre'
                ),
              ];
              return pres.some((el) => el.scrollWidth > el.clientWidth + 1);
            }"""
        )
        assert prose and captioned and plain
        _aligned(prose, captioned)
        _aligned(prose, plain)
        assert inner is True
    finally:
        _close(context, page)


@pytest.mark.browser
def test_wide_components_are_not_forced_to_reading_width(
    built_width_contract_site: BuiltWidthContractSite,
    shared_browser: Browser,
) -> None:
    built = built_width_contract_site()
    context, page = _open(shared_browser, built, PROSE_PAGE, width=1920, height=1080)
    try:
        prose = measure_edges(page, f"{REFERENCE_BOX_NORMAL} section > p")
        figure = measure_edges(page, "figure")
        admonition = measure_edges(page, ".admonition")
        assert prose and figure and admonition
        assert figure["width"] > prose["width"] + EDGE_TOLERANCE_PX
        assert admonition["width"] > prose["width"] + EDGE_TOLERANCE_PX
    finally:
        _close(context, page)

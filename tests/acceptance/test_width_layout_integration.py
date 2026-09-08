"""Issue #205: 内容幅（B/#203）× layout shell（C/#204）の結合回帰。

B と C の単体契約を丸写しせず、両者が合成されて初めて現れる境界だけを検証する。
測定規則は Spec §4.6 C4（境界一致 2 CSS px、document 横 overflow 1 CSS px、
border-box を getBoundingClientRect で測る）。fixture は読み取り専用（#202 凍結）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from acceptance.width_contract import (
    CODE_OUTER_PLAIN,
    CONTRACT_VIEWPORTS,
    EDGE_TOLERANCE_PX,
    OVERFLOW_TOLERANCE_PX,
    REFERENCE_BOX_NORMAL,
    REFERENCE_BOX_POST,
    WRAPPER_SELECTOR,
    document_overflow,
    measure_edges,
    measure_reference_box,
)
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from acceptance.conftest import AcceptanceSite, ProjectFactory
    from acceptance.width_contract import ElementEdges
    from playwright.sync_api import Page

POST_PAGE = "posts/width-post.html"
NORMAL_PAGE = "normal.html"
TABLES_PAGE = "tables.html"
CODE_PAGE = "code.html"
PROSE_PAGE = "prose.html"

#: T6 の実画面証拠（補助。合否判定は常に数値 assertion）。実パスを ledger に記録する。
EVIDENCE_DIR = Path("/tmp/issue-205-evidence")

#: rail の出ない最小 2 列 shell（C の実証済みパターンを踏襲。100% は D の追加）。
NO_RAIL_FILES = {"about.rst": "About\n=====\n\nA plain page that is not a post.\n"}
NO_RAIL_CONFIG: dict[str, object] = {
    "maatlog_default_author": None,
    "maatlog_content_width": "100%",
}


def _aligned(a: ElementEdges, b: ElementEdges) -> None:
    assert abs(a["left"] - b["left"]) <= EDGE_TOLERANCE_PX, (a, b)
    assert abs(a["right"] - b["right"]) <= EDGE_TOLERANCE_PX, (a, b)


def _inside(box: ElementEdges, reference: ElementEdges) -> None:
    assert box["left"] >= reference["left"] - EDGE_TOLERANCE_PX, (box, reference)
    assert box["right"] <= reference["right"] + EDGE_TOLERANCE_PX, (box, reference)


def _shell_metrics(page: Page) -> dict[str, Any]:
    """shell・main・rail・本文 prose の合成ボックスを 1 回の evaluate で測る。"""
    return cast(
        dict[str, Any],
        page.evaluate(
            """() => {
              const box = (selector) => {
                const element = document.querySelector(selector);
                return element ? element.getBoundingClientRect() : null;
              };
              const layoutEl = document.querySelector('.maatlog-layout');
              const mainEl = document.querySelector('.maatlog-layout-main');
              const layout = box('.maatlog-layout');
              const main = box('.maatlog-layout-main');
              const rail = box('.maatlog-right-rail');
              const prose =
                box('.maatlog-post-body section > p') ||
                box('.maatlog-layout-page-normal .body section > p') ||
                box('.maatlog-layout-page-normal .body p');
              const gap = layoutEl
                ? parseFloat(getComputedStyle(layoutEl).columnGap
                    || getComputedStyle(layoutEl).gap)
                : NaN;
              const cap = mainEl
                ? parseFloat(getComputedStyle(mainEl).maxWidth)
                : NaN;
              const pad = layoutEl
                ? parseFloat(getComputedStyle(layoutEl).paddingLeft)
                : NaN;
              const round = (value) => (value == null ? null : Math.round(value));
              return {
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
                viewport: document.documentElement.clientWidth,
                hasRail: Boolean(document.querySelector('.maatlog-layout-has-rail')),
                layoutLeft: round(layout && layout.left),
                layoutRight: round(layout && layout.right),
                layoutWidth: round(layout && layout.width),
                layoutPadding: Number.isFinite(pad) ? Math.round(pad) : null,
                mainLeft: round(main && main.left),
                mainRight: round(main && main.right),
                mainWidth: round(main && main.width),
                mainCap: Number.isFinite(cap) ? Math.round(cap) : null,
                railLeft: round(rail && rail.left),
                railWidth: round(rail && rail.width),
                proseRight: round(prose && prose.right),
                proseWidth: round(prose && prose.width),
                gap: Number.isFinite(gap) ? Math.round(gap) : null,
              };
            }"""
        ),
    )


@pytest.mark.browser
@pytest.mark.parametrize("value", ["100%", "clamp(42rem, 70vw, 90rem)"])
def test_content_width_never_escapes_capped_main(width_contract_site: AcceptanceSite, value: str) -> None:
    """T1（C2×C5、AC2/AC3/AC4）: cap 到達域で本文 4 種が main を突き抜けない。

    3840 では clamp(42rem, 70vw, 90rem) = 1440px、参照ボックスは capped main
    （約 1152px）より狭いため、% も CSS 関数も main 内で解決されなければならない。
    """
    result = width_contract_site.build(
        "html",
        theme="maatlog-default",
        config_overrides={"maatlog_content_width": value},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 3840, "height": 2160})
        try:
            page.goto(result.path(POST_PAGE).resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            prose = measure_edges(page, f"{REFERENCE_BOX_POST} section > p")
            heading = measure_edges(page, f"{REFERENCE_BOX_POST} section > h2")
            wrapper = measure_edges(page, f"{REFERENCE_BOX_POST} {WRAPPER_SELECTOR}")
            code = measure_edges(page, f"{REFERENCE_BOX_POST} {CODE_OUTER_PLAIN}")
            main = measure_edges(page, ".maatlog-layout-main")
            assert metrics["mainCap"] is not None and main and prose and heading and wrapper and code
            assert main["width"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, (main, metrics)
            for box in (prose, heading, wrapper, code):
                _inside(box, main)
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_viewport_growth_is_absorbed_outside_the_shell(
    width_contract_site: AcceptanceSite,
) -> None:
    """T2（C6×C2、AC4）: 4K の viewport 増分は shell 外部の余白が吸収する。

    shell は中央寄せ、main は cap 以下、既定 content width（clamp 上限 60rem=960px）
    は 4K の capped main（72rem=1152px）より狭く、残り幅は意図した余白。
    """
    result = width_contract_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 3840, "height": 2160})
        try:
            page.goto(result.path(POST_PAGE).resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            assert metrics["hasRail"] is True, metrics
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
            left = metrics["layoutLeft"]
            right = metrics["viewport"] - metrics["layoutRight"]
            assert abs(left - right) <= EDGE_TOLERANCE_PX, metrics
            # 外側余白は layout padding（gutter）より大きい = viewport 増分の吸収先
            assert left > (metrics["layoutPadding"] or 0) + EDGE_TOLERANCE_PX, metrics
            assert metrics["mainWidth"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, metrics
            # 本文は main より狭い（残り幅は意図した余白として区別される）
            assert metrics["proseWidth"] < metrics["mainWidth"] - EDGE_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_body_rail_distance_is_separate_from_main_rail_gap(
    width_contract_site: AcceptanceSite,
) -> None:
    """T3 前半（C6、AC4）: 本文–rail 距離と main–rail gap は別物。

    既定 content width（1920 で約 691px）は main（約 826px）より狭く、
    残り幅は意図した余白。rail 左端から見た本文の距離は gap より大きい。
    """
    result = width_contract_site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path(POST_PAGE).resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            assert metrics["hasRail"] is True, metrics
            assert metrics["railLeft"] is not None and metrics["mainRight"] is not None
            assert metrics["proseRight"] is not None and metrics["gap"] is not None
            main_rail = metrics["railLeft"] - metrics["mainRight"]
            body_rail = metrics["railLeft"] - metrics["proseRight"]
            assert abs(main_rail - metrics["gap"]) <= EDGE_TOLERANCE_PX, metrics
            assert body_rail > main_rail + EDGE_TOLERANCE_PX, metrics
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_full_content_width_fills_main_in_two_column_shell(
    make_project: ProjectFactory,
) -> None:
    """T3 後半（C2×C6、AC3/AC4）: rail なし 2 列 shell でも 100% = 中央列内の
    利用可能幅（viewport 全幅ではない）。shell は中央寄せのまま。
    """
    result = make_project(files=NO_RAIL_FILES, theme="maatlog-default", config=NO_RAIL_CONFIG).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 3840, "height": 2160})
        try:
            page.goto(result.path("about.html").resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            reference = measure_reference_box(page, REFERENCE_BOX_NORMAL)
            prose = measure_edges(page, f"{REFERENCE_BOX_NORMAL} p")
            rail = measure_edges(page, ".maatlog-right-rail")
            assert rail is None, metrics
            assert reference and prose, metrics
            _aligned(prose, reference)  # 100%: 本文は参照ボックスを満たす
            _inside(prose, measure_edges(page, ".maatlog-layout-main") or prose)
            left = metrics["layoutLeft"]
            right = metrics["viewport"] - metrics["layoutRight"]
            assert abs(left - right) <= EDGE_TOLERANCE_PX, metrics
            assert metrics["mainWidth"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, metrics
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_nested_percent_survives_main_cap(width_contract_site: AcceptanceSite) -> None:
    """T5（C1×C2×C5、AC2/AC3）: 90% は cap 到達域でも一度だけ解決され、
    入れ子リストは再縮小しない。参照ボックスは capped main 内に収まる。
    """
    result = width_contract_site.build(
        "html",
        theme="maatlog-default",
        config_overrides={"maatlog_content_width": "90%"},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 3840, "height": 2160})
        try:
            page.goto(result.path(PROSE_PAGE).resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            reference = measure_reference_box(page, REFERENCE_BOX_NORMAL)
            prose = measure_edges(page, f"{REFERENCE_BOX_NORMAL} section > p")
            widths = page.evaluate(
                """() => {
                  const outer = document.querySelector(
                    '.maatlog-layout-page-normal .body section > ul'
                  );
                  const inner = outer ? outer.querySelector('ul') : null;
                  return {
                    outer: outer ? Math.round(outer.getBoundingClientRect().width) : null,
                    inner: inner ? Math.round(inner.getBoundingClientRect().width) : null,
                  };
                }"""
            )
            assert reference and prose
            assert metrics["mainWidth"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, metrics
            _inside(reference, measure_edges(page, ".maatlog-layout-main") or reference)
            expected = round(reference["width"] * 0.9)
            assert abs(prose["width"] - expected) <= EDGE_TOLERANCE_PX, (prose, expected)
            # 入れ子は再縮小しない（B の 1280 単体を 4K capped main で確認）
            assert widths["outer"] is not None and widths["inner"] is not None
            assert widths["inner"] > round(widths["outer"] * 0.9) + EDGE_TOLERANCE_PX, widths
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_wide_components_keep_main_width_under_narrow_content_setting(
    site: AcceptanceSite, magazine_site: AcceptanceSite
) -> None:
    """T4（C3×C5、AC5）: 狭い content width 設定下でも hero / card grid /
    magazine は main 幅を使い続ける（content width に一律縮小しない）。
    """
    result = site.build(
        "html",
        theme="maatlog-default",
        config_overrides={"maatlog_content_width": "90%"},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            # hero（maattop）: 本文より広く、main 内
            page.goto(result.path("posts/hero-post.html").resolve().as_uri(), wait_until="load")
            hero = measure_edges(page, ".maatlog-post-top-image")
            prose = measure_edges(page, f"{REFERENCE_BOX_POST} section > p")
            main = measure_edges(page, ".maatlog-layout-main")
            assert hero and prose and main, "hero-post の構造確認（Spec R3 contingency 対象）"
            assert hero["width"] > prose["width"] + EDGE_TOLERANCE_PX, (hero, prose)
            # content width（90%）に縮められていない判別: hero > main 幅の 90%
            assert hero["width"] > round(main["width"] * 0.9) + EDGE_TOLERANCE_PX, (hero, main)
            _inside(hero, main)
            assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX

            # home の card grid: 縮小されず main 内
            page.goto(result.path("index.html").resolve().as_uri(), wait_until="load")
            grid = measure_edges(page, ".maatlog-post-grid, .maatlog-post-list")
            main = measure_edges(page, ".maatlog-layout-main")
            assert grid and main
            assert grid["width"] > round(main["width"] * 0.9) + EDGE_TOLERANCE_PX, (grid, main)
            assert grid["width"] <= main["width"] + EDGE_TOLERANCE_PX, (grid, main)
            assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX

            # archive: main 内・overflow なし（回帰）
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            archive = measure_edges(page, ".maatlog-archive")
            main = measure_edges(page, ".maatlog-layout-main")
            assert archive and main
            assert archive["width"] <= main["width"] + EDGE_TOLERANCE_PX, (archive, main)
            assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX

            # magazine home × 90% 設定: 内部列構成を縮めない・overflow なし
            mresult = magazine_site.build(
                "html",
                theme="maatlog-default",
                config_overrides={"maatlog_content_width": "90%"},
            )
            page.goto(mresult.path("index.html").resolve().as_uri(), wait_until="load")
            metrics = _shell_metrics(page)
            assert metrics["mainWidth"] <= metrics["mainCap"] + EDGE_TOLERANCE_PX, metrics
            assert metrics["overflow"] <= OVERFLOW_TOLERANCE_PX, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (3840, 2160)])
def test_table_rule_continuity_inside_centered_capped_shell(
    width_contract_site: AcceptanceSite, width: int, height: int
) -> None:
    """T6（AC1/AC6）: 中央寄せ capped shell の中でも罫線が表の右端まで連続し、
    幅広表は wrapper 内スクロールの右端まで罫線が連続する。実画面の
    スクリーンショットは補助証拠（合否は数値 assertion が正本）。
    """
    result = width_contract_site.build("html", theme="maatlog-default")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(result.path(TABLES_PAGE).resolve().as_uri(), wait_until="load")
            page.screenshot(path=str(EVIDENCE_DIR / f"tables-{width}-top.png"))

            # 短い表（最初の wrapper の表）: 最終列セル右端 == 表右端、表幅 == wrapper 幅
            short = page.evaluate(
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
            assert short is not None
            assert abs(short["cellRight"] - short["tableRight"]) <= EDGE_TOLERANCE_PX, short
            assert abs(short["tableWidth"] - short["wrapperWidth"]) <= EDGE_TOLERANCE_PX, short

            # 幅広表（16 列・nowrap。fixture 設計上全 CONTRACT_VIEWPORTS でスクロール発生）:
            # 右端までスクロールした後も最終列セル右端 == 表右端 == wrapper 右端付近
            wide = page.evaluate(
                """() => {
                  const wrappers = [...document.querySelectorAll('.maatlog-table-wrapper')];
                  const target = wrappers.find((w) => w.scrollWidth > w.clientWidth + 1);
                  if (!target) return null;
                  target.scrollLeft = target.scrollWidth;
                  const table = target.querySelector('table.docutils');
                  const last = table.querySelector('thead th:last-child, tbody tr td:last-child');
                  const tableBox = table.getBoundingClientRect();
                  const wrapperBox = target.getBoundingClientRect();
                  return {
                    scrolled: target.scrollLeft > 0,
                    tableRight: Math.round(tableBox.right),
                    cellRight: Math.round(last.getBoundingClientRect().right),
                    wrapperRight: Math.round(wrapperBox.right),
                  };
                }"""
            )
            assert wide is not None, "16 列の幅広表は全 viewport でスクロールする fixture 設計"
            assert wide["scrolled"] is True, wide
            assert abs(wide["cellRight"] - wide["tableRight"]) <= EDGE_TOLERANCE_PX, wide
            assert abs(wide["tableRight"] - wide["wrapperRight"]) <= EDGE_TOLERANCE_PX, wide
            page.screenshot(path=str(EVIDENCE_DIR / f"tables-{width}-wide-scrolled.png"))

            # 表 wrapper は capped main の内側
            main = measure_edges(page, ".maatlog-layout-main")
            wrapper = measure_edges(page, WRAPPER_SELECTOR)
            assert main and wrapper
            _inside(wrapper, main)
            assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX
        finally:
            page.close()
            browser.close()


#: T7 の対象ページと参照ボックス（page, reference box selector）
T7_PAGES: tuple[tuple[str, str], ...] = (
    (POST_PAGE, REFERENCE_BOX_POST),
    (NORMAL_PAGE, REFERENCE_BOX_NORMAL),
    (TABLES_PAGE, REFERENCE_BOX_NORMAL),
    (CODE_PAGE, REFERENCE_BOX_NORMAL),
)


@pytest.mark.browser
@pytest.mark.parametrize("value", ["90%", "100%"])
@pytest.mark.parametrize(("width", "height"), CONTRACT_VIEWPORTS)
def test_percent_settings_do_not_overflow_across_contract_viewports(
    width_contract_site: AcceptanceSite, value: str, width: int, height: int
) -> None:
    """T7（AC8×AC3×AC6）: B は 90%/100% を 390/3840 のみ、C は全 viewport を
    既定設定のみ測った。D は % 設定 × 全 CONTRACT_VIEWPORTS の交差を埋める。
    """
    result = width_contract_site.build(
        "html",
        theme="maatlog-default",
        config_overrides={"maatlog_content_width": value},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for relative, reference_box in T7_PAGES:
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                main = measure_edges(page, ".maatlog-layout-main")
                prose = measure_edges(page, f"{reference_box} section > p")
                assert main and prose, (relative, width, value)
                _inside(prose, main)
                if relative == TABLES_PAGE:
                    wrapper = measure_edges(page, WRAPPER_SELECTOR)
                    assert wrapper is not None, (relative, width, value)
                    _inside(wrapper, main)
                assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX, (
                    relative,
                    width,
                    value,
                )
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_light_dark_and_js_disabled_width_regression(
    width_contract_site: AcceptanceSite,
) -> None:
    """T8（AC7、C4「light/dark の回帰は D が両方で確認」）: 幅契約は
    light/dark・JS 有無で変わらない。wrapper の tabindex（キーボード
    スクロール可能構造）は JS 無効でも存在し、dark は実際に適用される。
    """
    result = width_contract_site.build("html", theme="maatlog-default")
    combos: tuple[tuple[str, bool], ...] = (
        ("light", True),
        ("dark", True),
        ("light", False),
        ("dark", False),
    )
    backgrounds: dict[tuple[str, bool], str] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for scheme, js in combos:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    color_scheme=scheme,
                    java_script_enabled=js,
                )
                page = context.new_page()
                try:
                    for relative in (POST_PAGE, TABLES_PAGE):
                        page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                        assert document_overflow(page) <= OVERFLOW_TOLERANCE_PX, (
                            scheme,
                            js,
                            relative,
                        )
                        tab = page.evaluate(
                            """() => {
                              const wrapper = document.querySelector('.maatlog-table-wrapper');
                              return wrapper ? wrapper.getAttribute('tabindex') : null;
                            }"""
                        )
                        assert tab == "0", (scheme, js, relative)
                        if relative == POST_PAGE:
                            backgrounds[(scheme, js)] = cast(
                                str,
                                page.evaluate("() => getComputedStyle(document.body).backgroundColor"),
                            )
                finally:
                    page.close()
                    context.close()
        finally:
            browser.close()
    # dark が実際に適用されている証拠（幅・構造は scheme 非依存なので背景色で確認）
    assert backgrounds[("light", True)] != backgrounds[("dark", True)], backgrounds
    assert backgrounds[("light", False)] == backgrounds[("light", True)], backgrounds

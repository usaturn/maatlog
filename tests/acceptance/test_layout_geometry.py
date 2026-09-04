from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

import pytest
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.conftest import AcceptanceSite, ProjectFactory

WIDE_VIEWPORTS = ((1280, 720), (1920, 1080), (2560, 1440))
# Issue #110: prose / main width policy across Wide → 4K viewports.
WIDTH_POLICY_VIEWPORTS = (
    (1280, 720),
    (1920, 1080),
    (2560, 1440),
    (2880, 1620),
    (3840, 2160),
)
REPRESENTATIVE_PAGES = (
    "index.html",
    "guide.html",
    "blog.html",
    "posts/rst-post.html",
)
# body margin (~8px) + layout padding (1rem). Must stay padding-sized as
# viewport grows; the old 1fr rails produced 300px+ gutters at 1920.
MAX_OUTER_GUTTER_PX = 64
# Fluid content-width floor / ceiling (16px root): clamp(42rem, …, 60rem).
PROSE_MIN_PX = 660  # ~42rem with rounding slack
PROSE_MAX_PX = 970  # ~60rem with rounding slack
# At 2560px the previous 42rem fixed line must already have widened.
PROSE_WIDE_MIN_PX = 740


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


# 5 記事 = featured 3 枚 + グリッド 2 枚。受け入れプロジェクトは公開記事が 2 本しか
# 無く、3 枚 Bento も .maatlog-post-grid も出ないので、ここだけ使い捨ての
# プロジェクトを組む。固定コーパスを増やすと test_mvp の期待値が連鎖的に壊れる。
BENTO_PROJECT = {
    f"post{n}.md": f"""---
maatlog-post: true
maatlog-slug: post{n}
maatlog-published-at: 2026-07-2{n}T09:00:00Z
maatlog-tags: [sphinx]
---
# Post {n}

Body of post {n}.
"""
    for n in (1, 2, 3, 4, 5)
}


@pytest.mark.browser
def test_home_featured_lead_card_is_wider_than_its_neighbours(
    make_project: ProjectFactory,
) -> None:
    # Bento の狙いは「先頭記事が視覚的に強い」こと。幅で固定する。
    result = make_project(files=BENTO_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            widths = page.evaluate(
                """() => Array.from(
                     document.querySelectorAll('.maatlog-post-featured .maatlog-post-card')
                   ).map((card) => Math.round(card.getBoundingClientRect().width))"""
            )

            assert len(widths) == 3, widths
            assert widths[0] > widths[1], widths
            assert widths[1] == widths[2], widths
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_home_latest_cards_form_a_multi_column_grid(make_project: ProjectFactory) -> None:
    result = make_project(files=BENTO_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            lefts = page.evaluate(
                """() => Array.from(
                     document.querySelectorAll('.maatlog-post-grid .maatlog-post-card')
                   ).map((card) => Math.round(card.getBoundingClientRect().left))"""
            )

            assert len(lefts) == 2, lefts
            assert len(set(lefts)) == 2, lefts
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_home_cards_collapse_to_one_column_on_mobile(make_project: ProjectFactory) -> None:
    result = make_project(files=BENTO_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            lefts = page.evaluate(
                """() => Array.from(
                     document.querySelectorAll('.maatlog-post-card')
                   ).map((card) => Math.round(card.getBoundingClientRect().left))"""
            )
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

            assert len(lefts) == 5, lefts
            assert len(set(lefts)) == 1, lefts
            assert overflow == 0
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_inline_post_reference_stays_inline(site: AcceptanceSite) -> None:
    # ``{maatlog:post}`` の出す <code class="maatlog-post"> が記事コンテナの
    # grid ルールを拾うと、インライン参照が全幅の空箱になる。
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("guide.html").resolve().as_uri(), wait_until="load")
            metrics = page.evaluate(
                """() => {
                  const ref = document.querySelector('code.maatlog-post');
                  if (!ref) return null;
                  const box = ref.getBoundingClientRect();
                  const main = document.querySelector('.maatlog-layout-main').getBoundingClientRect();
                  return {
                    height: Math.round(box.height),
                    width: Math.round(box.width),
                    main_width: Math.round(main.width),
                    display: getComputedStyle(ref).display,
                  };
                }"""
            )
            assert metrics is not None, "guide.html renders no {maatlog:post} reference"
            assert metrics["display"] != "grid", metrics
            assert metrics["height"] <= 40, metrics
            assert metrics["width"] < metrics["main_width"] / 2, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_wide_tables_scroll_without_widening_the_page(site: AcceptanceSite) -> None:
    # 表は内側でスクロールしてよいが、ページ本体を広げてはいけない。
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(result.path("guide.html").resolve().as_uri(), wait_until="load")
            metrics = page.evaluate(
                """() => {
                  const table = document.querySelector('.maatlog-layout-main table.docutils');
                  return {
                    page_overflow: document.documentElement.scrollWidth
                      - document.documentElement.clientWidth,
                    table_width: table ? Math.round(table.getBoundingClientRect().width) : null,
                    table_scrolls: table ? table.scrollWidth > table.clientWidth : null,
                    viewport: document.documentElement.clientWidth,
                  };
                }"""
            )
            assert metrics["table_width"] is not None, "guide.html renders no table"
            assert metrics["page_overflow"] == 0, metrics
            assert metrics["table_width"] <= metrics["viewport"], metrics
            assert metrics["table_scrolls"] is True, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_normal_page_prose_is_narrower_than_its_container(site: AcceptanceSite) -> None:
    # 通常ページのコンテナは main いっぱいのまま、段落だけが行長で止まる。
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path("guide.html").resolve().as_uri(), wait_until="load")
            body_width = _element_width(page, ".body")
            paragraph_width = page.evaluate(
                """() => {
                  const p = document.querySelector('.body > section > p');
                  return p ? Math.round(p.getBoundingClientRect().width) : null;
                }"""
            )
            assert paragraph_width is not None, "guide.html renders no top-level paragraph"
            assert paragraph_width <= PROSE_MAX_PX, paragraph_width
            assert body_width > paragraph_width, (body_width, paragraph_width)
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_prose_grows_with_wide_viewports_but_stays_below_main(site: AcceptanceSite) -> None:
    # Issue #110: content-width / main-width を fluid にし、1280 では現行相当、
    # 2560 以上では 42rem 固定より明確に広げ、4K でも上限を超えない。
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            prose_by_width: dict[int, int] = {}
            for width, height in WIDTH_POLICY_VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
                    metrics = page.evaluate(
                        """() => {
                          const main = document.querySelector('.maatlog-layout-main');
                          const prose = document.querySelector('.maatlog-post-body p');
                          const highlight = document.querySelector('.maatlog-post-body .highlight');
                          if (!main || !prose) return null;
                          return {
                            overflow: document.documentElement.scrollWidth
                              - document.documentElement.clientWidth,
                            main: Math.round(main.getBoundingClientRect().width),
                            prose: Math.round(prose.getBoundingClientRect().width),
                            code: highlight
                              ? Math.round(highlight.getBoundingClientRect().width)
                              : null,
                          };
                        }"""
                    )
                    assert metrics is not None, f"missing main/prose @{width}"
                    assert metrics["overflow"] == 0, f"overflow @{width}"
                    assert PROSE_MIN_PX <= metrics["prose"] <= PROSE_MAX_PX, metrics
                    assert metrics["main"] > metrics["prose"], metrics
                    if metrics["code"] is not None:
                        assert metrics["code"] > metrics["prose"], metrics
                    prose_by_width[width] = metrics["prose"]
                finally:
                    page.close()

            assert prose_by_width[1280] <= 690, prose_by_width
            assert prose_by_width[1920] >= prose_by_width[1280], prose_by_width
            assert prose_by_width[2560] >= PROSE_WIDE_MIN_PX, prose_by_width
            assert prose_by_width[3840] > prose_by_width[2560], prose_by_width
            assert prose_by_width[3840] <= PROSE_MAX_PX, prose_by_width
        finally:
            browser.close()


# ページ種別を 1 つずつ。home = bento、archive = カードグリッド、
# post = editorial header、normal = 表とコードブロック。
MODERNIZED_PAGES = (
    "home.html",
    "blog.html",
    "posts/rst-post.html",
    "guide.html",
    "api.html",
)


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1024, 768), (390, 844)])
def test_every_page_kind_stays_within_the_viewport(site: AcceptanceSite, width: int, height: int) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for relative in MODERNIZED_PAGES:
                target = result.path(relative)
                assert target.exists(), f"{relative} was not built"
                page.goto(target.resolve().as_uri(), wait_until="load")
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                assert overflow == 0, f"{relative}@{width}: overflow {overflow}px"
        finally:
            page.close()
            browser.close()

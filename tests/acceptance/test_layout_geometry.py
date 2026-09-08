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
              const rail = box('.maatlog-right-rail');
              const rightEdge = rail ? rail.right : main.right;
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


@pytest.mark.browser
def test_wide_shell_sends_surplus_viewport_to_outer_gutters(
    site: AcceptanceSite,
) -> None:
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            gutters_by_width: dict[int, int] = {}
            mains_by_width: dict[int, int] = {}
            for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)):
                page = browser.new_page(viewport={"width": width, "height": height})
                try:
                    page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
                    metrics = page.evaluate(
                        """() => {
                          const layout = document.querySelector('.maatlog-layout');
                          const main = document.querySelector('.maatlog-layout-main');
                          const nav = document.querySelector('.maatlog-nav');
                          const rail = document.querySelector('.maatlog-right-rail');
                          const layoutBox = layout.getBoundingClientRect();
                          const mainBox = main.getBoundingClientRect();
                          const cap = parseFloat(getComputedStyle(main).maxWidth);
                          return {
                            overflow: document.documentElement.scrollWidth
                              - document.documentElement.clientWidth,
                            viewport: document.documentElement.clientWidth,
                            layoutLeft: Math.round(layoutBox.left),
                            layoutRight: Math.round(layoutBox.right),
                            layoutWidth: Math.round(layoutBox.width),
                            mainWidth: Math.round(mainBox.width),
                            navWidth: nav ? Math.round(nav.getBoundingClientRect().width) : 0,
                            railWidth: rail ? Math.round(rail.getBoundingClientRect().width) : 0,
                            mainCap: Number.isFinite(cap) ? Math.round(cap) : null,
                          };
                        }"""
                    )
                    assert metrics["overflow"] <= 1, metrics
                    left = metrics["layoutLeft"]
                    right = metrics["viewport"] - metrics["layoutRight"]
                    assert abs(left - right) <= 2, metrics
                    if metrics["mainCap"] is not None:
                        assert metrics["mainWidth"] <= metrics["mainCap"] + 2, metrics
                    gutters_by_width[width] = left
                    mains_by_width[width] = metrics["mainWidth"]
                finally:
                    page.close()
            assert gutters_by_width[1280] <= 64, gutters_by_width
            assert gutters_by_width[1920] > gutters_by_width[1280], gutters_by_width
            assert gutters_by_width[3840] > gutters_by_width[1920], gutters_by_width
            # 2560→3840 の main は clamp の preferred に従い 72rem 天井まで伸びる
            # （Spec §1.6: 941px → 1152px）。天井超過の禁止が契約の意味。
            assert mains_by_width[3840] <= 1152 + 2, mains_by_width
            assert mains_by_width[3840] >= mains_by_width[2560], mains_by_width
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

MAGAZINE_COLUMN_PROJECT = {
    f"post{n}.md": f"""---
maatlog-post: true
maatlog-slug: post{n}
maatlog-published-at: 2026-07-2{n}T09:00:00Z
maatlog-tags: [sphinx]
---
# Post {n}

Body of post {n}.
"""
    for n in (1, 2, 3, 4, 5, 6)
}


NINE_POST_PROJECT = {
    f"post{n}.md": f"""---
maatlog-post: true
maatlog-slug: post{n}
maatlog-published-at: 2026-07-{n:02d}T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [docs]
maatlog-authors: [alice]
---
# Post {n}

Body of post {n}.
"""
    for n in range(1, 10)
}


def _first_row_column_count(metrics: dict[str, object]) -> int:
    tops = cast("list[int]", metrics["tops"])
    lefts = cast("list[int]", metrics["lefts"])
    first_row = [left for left, top in zip(lefts, tops, strict=True) if top == min(tops)]
    return len(set(first_row))


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (2560, 1440), (3840, 2160)])
def test_home_latest_stays_three_columns_on_wide_viewports(
    make_project: ProjectFactory,
    width: int,
    height: int,
) -> None:
    result = make_project(files=NINE_POST_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            latest = _card_row_metrics(page, '[data-maatlog-component="latest"]')
            featured = _card_row_metrics(page, '[data-maatlog-component="featured"]')
            assert latest["count"] == 6, latest
            assert featured["count"] == 3, featured
            assert latest["overflow"] == 0, latest
            # NOTE (Issue #204, parent ruling (a)): the wide shell is capped at
            # --maatlog-main-width (mains ~826px@1920, ~941px@2560, ~1152px@3840
            # per Spec §1.6), so the latest grid fits 2 columns at 1920/2560
            # and returns to 3 at 3840. Counts and overflow are unchanged.
            expected_columns = 3 if width == 3840 else 2
            assert _first_row_column_count(latest) == expected_columns, latest
            widths = page.evaluate(
                """() => Array.from(
                     document.querySelectorAll(
                       '[data-maatlog-component="featured"] .maatlog-post-card'
                     )
                   ).map((card) => Math.round(card.getBoundingClientRect().width))"""
            )
            assert widths[0] > widths[1] == widths[2], widths
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_home_latest_is_two_columns_at_1280_with_six_cards(
    make_project: ProjectFactory,
) -> None:
    result = make_project(files=NINE_POST_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            latest = _card_row_metrics(page, '[data-maatlog-component="latest"]')
            assert latest["count"] == 6, latest
            assert latest["overflow"] == 0, latest
            assert _first_row_column_count(latest) == 2, latest
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), [(768, 1024), (390, 844)])
def test_home_magazine_is_one_column_on_narrow_viewports(
    make_project: ProjectFactory,
    width: int,
    height: int,
) -> None:
    result = make_project(files=NINE_POST_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            featured = _card_row_metrics(page, '[data-maatlog-component="featured"]')
            latest = _card_row_metrics(page, '[data-maatlog-component="latest"]')
            assert featured["count"] == 3, featured
            assert latest["count"] == 6, latest
            assert _first_row_column_count(featured) == 1, featured
            assert _first_row_column_count(latest) == 1, latest
            assert featured["overflow"] == 0, featured
            assert latest["overflow"] == 0, latest
        finally:
            page.close()
            browser.close()


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _n_posts(count: int, *, extra: dict[str, str] | None = None) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {
        f"post{n}.md": f"""---
maatlog-post: true
maatlog-slug: post{n}
maatlog-published-at: 2026-07-{n:02d}T09:00:00Z
maatlog-tags: [sphinx]
---
# Post {n}

Body of post {n}.
"""
        for n in range(1, count + 1)
    }
    if extra:
        files.update(extra)
    return files


@pytest.mark.browser
def test_single_featured_card_spans_the_container(make_project: ProjectFactory) -> None:
    result = make_project(files=_n_posts(1)).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            metrics = page.evaluate(
                """() => {
                  const box = (selector) => {
                    const el = document.querySelector(selector);
                    return el ? Math.round(el.getBoundingClientRect().width) : null;
                  };
                  return {
                    featured: box('[data-maatlog-component="featured"]'),
                    card: box('.maatlog-post-card-lead'),
                    latest: document.querySelector('[data-maatlog-component="latest"]'),
                  };
                }"""
            )
            assert metrics["featured"] is not None, metrics
            assert metrics["card"] is not None, metrics
            assert abs(metrics["card"] - metrics["featured"]) <= 2, metrics
            assert metrics["latest"] is None
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_two_featured_cards_share_one_row(make_project: ProjectFactory) -> None:
    result = make_project(files=_n_posts(2)).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            featured = _card_row_metrics(page, '[data-maatlog-component="featured"]')
            assert featured["count"] == 2, featured
            assert len(set(cast("list[int]", featured["tops"]))) == 1, featured
            assert _first_row_column_count(featured) == 2, featured
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_lead_image_uses_four_by_three_cover(make_project: ProjectFactory) -> None:
    files = _n_posts(3)
    files["post3.md"] = """---
maatlog-post: true
maatlog-slug: post3
maatlog-published-at: 2026-07-03T09:00:00Z
maatlog-image: images/cover.png
---
# Post 3

Lead with image.
"""
    files["images/cover.png"] = PNG_1X1
    result = make_project(files=files).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            image = page.evaluate(
                """() => {
                  const el = document.querySelector(
                    '.maatlog-post-card-lead .maatlog-post-card-image'
                  );
                  if (!el) return null;
                  const style = getComputedStyle(el);
                  return {
                    ratio: style.aspectRatio,
                    fit: style.objectFit,
                  };
                }"""
            )
            assert image is not None
            assert image["ratio"] in {"4 / 3", "1.33333"}, image
            assert image["fit"] == "cover", image
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_long_titles_do_not_overflow_on_mobile(make_project: ProjectFactory) -> None:
    files = _n_posts(
        3,
        extra={
            "post3.md": """---
maatlog-post: true
maatlog-slug: post3
maatlog-published-at: 2026-07-03T09:00:00Z
---
# 日本語のとても長い見出しでカードから本文がはみ出さないことを確認するためのタイトル

Body.
""",
            "post2.md": """---
maatlog-post: true
maatlog-slug: post2
maatlog-published-at: 2026-07-02T09:00:00Z
---
# SupercalifragilisticexpialidociousUnusuallyLongEnglishTitleWithoutSpaces

Body.
""",
        },
    )
    result = make_project(files=files).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            metrics = page.evaluate(
                """() => {
                  const titles = Array.from(
                    document.querySelectorAll('.maatlog-post-card-title')
                  );
                  return {
                    overflow: document.documentElement.scrollWidth
                      - document.documentElement.clientWidth,
                    nowrap: titles.map((el) => getComputedStyle(el).whiteSpace),
                  };
                }"""
            )
            assert metrics["overflow"] == 0, metrics
            assert all(value != "nowrap" for value in metrics["nowrap"]), metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_non_home_archive_is_not_capped_at_three_columns(
    make_project: ProjectFactory,
) -> None:
    result = make_project(
        files=_home_files(NINE_POST_PROJECT),
        config={"maatlog_home_docname": "home"},
    ).build()
    html = result.path("blog.html").read_text(encoding="utf-8")
    assert 'data-maatlog-component="latest"' not in html
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            grid = _card_row_metrics(page, ".maatlog-post-grid")
            assert grid["count"] == 9, grid
            assert _first_row_column_count(grid) != 3, grid
        finally:
            page.close()
            browser.close()


def _home_files(posts: dict[str, str]) -> dict[str, str]:
    return {
        **posts,
        "home.md": "# Home\n\nWelcome.\n",
    }


def test_archive_home_emits_theme_api_lead_markup(
    make_project: ProjectFactory,
) -> None:
    result = make_project(files=MAGAZINE_COLUMN_PROJECT).build()
    html = result.path("blog.html").read_text(encoding="utf-8")
    assert 'data-maatlog-component="featured"' in html
    assert 'data-maatlog-component="latest"' in html
    assert "maatlog-post-card-lead" in html
    assert "maatlog-post-card-secondary" in html
    assert 'data-maatlog-card-variant="latest"' in html


@pytest.mark.browser
def test_home_type_scale_is_lead_then_secondary_then_latest(
    make_project: ProjectFactory,
) -> None:
    result = make_project(files=MAGAZINE_COLUMN_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            sizes = page.evaluate(
                """() => {
                  const px = (selector) => {
                    const el = document.querySelector(selector);
                    return el ? parseFloat(getComputedStyle(el).fontSize) : null;
                  };
                  return {
                    lead: px('.maatlog-post-card-lead .maatlog-post-card-title'),
                    secondary: px('.maatlog-post-card-secondary .maatlog-post-card-title'),
                    latest: px('[data-maatlog-card-variant="latest"] .maatlog-post-card-title'),
                  };
                }"""
            )
            assert sizes["lead"] is not None, sizes
            assert sizes["secondary"] is not None, sizes
            assert sizes["latest"] is not None, sizes
            assert sizes["lead"] > sizes["secondary"] > sizes["latest"], sizes
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_dedicated_home_keeps_magazine_layout(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_home_files(MAGAZINE_COLUMN_PROJECT),
        config={"maatlog_home_docname": "home"},
    ).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(result.path("home.html").resolve().as_uri(), wait_until="load")
            featured = _card_row_metrics(page, '[data-maatlog-component="featured"]')
            latest = _card_row_metrics(page, '[data-maatlog-component="latest"]')
            assert featured["count"] == 3, featured
            assert latest["count"] == 3, latest
            widths = page.evaluate(
                """() => Array.from(
                     document.querySelectorAll(
                       '[data-maatlog-component="featured"] .maatlog-post-card'
                     )
                   ).map((card) => Math.round(card.getBoundingClientRect().width))"""
            )
            assert widths[0] > widths[1], widths
            assert widths[1] == widths[2], widths
            tops = cast("list[int]", latest["tops"])
            lefts = cast("list[int]", latest["lefts"])
            first_row = [left for left, top in zip(lefts, tops, strict=True) if top == min(tops)]
            assert len(set(first_row)) >= 2, latest
        finally:
            page.close()
            browser.close()


def _card_row_metrics(page: Page, container: str) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        page.evaluate(
            """(container) => {
              const cards = Array.from(
                document.querySelectorAll(container + ' .maatlog-post-card')
              );
              return {
                count: cards.length,
                lefts: cards.map((card) => Math.round(card.getBoundingClientRect().left)),
                tops: cards.map((card) => Math.round(card.getBoundingClientRect().top)),
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
              };
            }""",
            container,
        ),
    )


@pytest.mark.browser
def test_home_latest_is_three_columns_on_wide_desktop(
    make_project: ProjectFactory,
) -> None:
    result = make_project(files=MAGAZINE_COLUMN_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            metrics = _card_row_metrics(page, ".maatlog-post-grid")
            assert metrics["count"] == 3, metrics
            assert metrics["overflow"] == 0, metrics
            tops = cast("list[int]", metrics["tops"])
            lefts = cast("list[int]", metrics["lefts"])
            first_row = [left for left, top in zip(lefts, tops, strict=True) if top == min(tops)]
            # NOTE (Issue #204, parent ruling (a)): at 1920 the capped main is
            # ~826px (Spec §1.6), so the grid fits 2 columns instead of 3.
            # Count and overflow are unchanged.
            assert len(set(first_row)) == 2, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_home_latest_is_two_columns_at_1280(
    make_project: ProjectFactory,
) -> None:
    result = make_project(files=MAGAZINE_COLUMN_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            metrics = _card_row_metrics(page, ".maatlog-post-grid")
            assert metrics["count"] == 3, metrics
            assert metrics["overflow"] == 0, metrics
            tops = cast("list[int]", metrics["tops"])
            lefts = cast("list[int]", metrics["lefts"])
            first_row = [left for left, top in zip(lefts, tops, strict=True) if top == min(tops)]
            assert len(set(first_row)) == 2, metrics
        finally:
            page.close()
            browser.close()


@pytest.mark.browser
def test_home_magazine_is_one_column_at_768(
    make_project: ProjectFactory,
) -> None:
    result = make_project(files=MAGAZINE_COLUMN_PROJECT).build()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 768, "height": 1024})
        try:
            page.goto(result.path("blog.html").resolve().as_uri(), wait_until="load")
            featured = _card_row_metrics(page, ".maatlog-post-featured")
            latest = _card_row_metrics(page, ".maatlog-post-grid")
            assert featured["count"] == 3, featured
            assert latest["count"] == 3, latest
            assert len(set(cast("list[int]", featured["lefts"]))) == 1, featured
            assert len(set(cast("list[int]", latest["lefts"]))) == 1, latest
            assert featured["overflow"] == 0
        finally:
            page.close()
            browser.close()


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
                  const wrapper = document.querySelector('.maatlog-layout-main .maatlog-table-wrapper');
                  return {
                    page_overflow: document.documentElement.scrollWidth
                      - document.documentElement.clientWidth,
                    wrapper_width: wrapper ? Math.round(wrapper.getBoundingClientRect().width) : null,
                    wrapper_scrolls: wrapper ? wrapper.scrollWidth > wrapper.clientWidth : null,
                    viewport: document.documentElement.clientWidth,
                  };
                }"""
            )
            assert metrics["wrapper_width"] is not None, "guide.html renders no table"
            assert metrics["page_overflow"] == 0, metrics
            assert metrics["wrapper_width"] <= metrics["viewport"], metrics
            assert metrics["wrapper_scrolls"] is True, metrics
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
                          const codeOuter = document.querySelector(
                            ".maatlog-post-body .literal-block-wrapper, .maatlog-post-body div[class*='highlight-']"
                          );
                          if (!main || !prose) return null;
                          return {
                            overflow: document.documentElement.scrollWidth
                              - document.documentElement.clientWidth,
                            main: Math.round(main.getBoundingClientRect().width),
                            prose: Math.round(prose.getBoundingClientRect().width),
                            code: codeOuter
                              ? Math.round(codeOuter.getBoundingClientRect().width)
                              : null,
                          };
                        }"""
                    )
                    assert metrics is not None, f"missing main/prose @{width}"
                    assert metrics["overflow"] == 0, f"overflow @{width}"
                    assert PROSE_MIN_PX <= metrics["prose"] <= PROSE_MAX_PX, metrics
                    assert metrics["main"] > metrics["prose"], metrics
                    if metrics["code"] is not None:
                        assert abs(metrics["code"] - metrics["prose"]) <= 2, metrics
                        assert metrics["code"] <= metrics["main"], metrics
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


class ProseMetrics(TypedDict):
    overflow: int
    prose_width: int
    prose_right: int
    main_right: int
    main_width: int


def _prose_metrics(page: Page) -> ProseMetrics:
    return cast(
        ProseMetrics,
        page.evaluate(
            """() => {
              const prose = document.querySelector('.maatlog-post-body p')
                ?? document.querySelector('.maatlog-layout-main .body p');
              const main = document.querySelector('.maatlog-layout-main');
              const proseBox = prose.getBoundingClientRect();
              const mainBox = main.getBoundingClientRect();
              return {
                overflow: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth,
                prose_width: Math.round(proseBox.width),
                prose_right: Math.round(proseBox.right),
                main_right: Math.round(mainBox.right),
                main_width: Math.round(mainBox.width),
              };
            }"""
        ),
    )


@pytest.mark.browser
def test_content_width_100_percent_fills_the_main_column(site: AcceptanceSite) -> None:
    """Issue #139: maatlog_content_width = "100%" で prose が中央列いっぱいになる。"""
    result = site.build(config_overrides={"maatlog_content_width": "100%"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 2560, "height": 1440})
            page.goto(result.path("posts/rst-post.html").resolve().as_uri(), wait_until="load")
            metrics = _prose_metrics(page)
        finally:
            browser.close()

    assert metrics["overflow"] == 0
    assert metrics["prose_width"] <= metrics["main_width"] + 2
    assert metrics["prose_width"] <= metrics["main_right"]
    # 右端は中央列の右端まで届く。差はレイアウトの padding 相当に収まる。
    assert metrics["main_right"] - metrics["prose_right"] <= MAX_OUTER_GUTTER_PX


@pytest.mark.browser
@pytest.mark.parametrize(("width", "height"), WIDTH_POLICY_VIEWPORTS + ((375, 667),))
def test_content_width_100_percent_never_scrolls_horizontally(
    site: AcceptanceSite,
    width: int,
    height: int,
) -> None:
    """行幅を広げても横スクロールは出さない。狭い viewport も含めて確認する。"""
    result = site.build(config_overrides={"maatlog_content_width": "100%"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            for name in REPRESENTATIVE_PAGES:
                page.goto(result.path(name).resolve().as_uri(), wait_until="load")
                metrics = _prose_metrics(page)
                assert metrics["overflow"] == 0, f"{name} at {width}x{height}"
        finally:
            browser.close()

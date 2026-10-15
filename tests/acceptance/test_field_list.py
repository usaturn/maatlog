"""Browser regression for body field lists laid out in two columns (Issue #21)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

import pytest
from acceptance.accessibility import axe_violations
from conftest import ProjectFactory

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Locator, Page

ROOT = Path(__file__).resolve().parents[2]
AXE_PATH = ROOT / "node_modules" / "axe-core" / "axe.min.js"

# Desktop and the phone width the Issue was reproduced at.
VIEWPORTS = ((1280, 900), (390, 844))

# Sub-pixel layout noise only.
TOLERANCE_PX = 1.5
# column-gap is 1rem; the stacked layout indented every dd by 40px.
MAX_COLUMN_GAP_PX = 24
# row-gap is 0.25rem; paragraph margins used to add 16px above and below.
MAX_ROW_GAP_PX = 8
# Same cap as basic.css: fit-content(30%).
NAME_COLUMN_RATIO = 0.3

LONG_NAME = "FieldNameWithoutAnyBreakOpportunityThatMustWrapInsideItsColumn"
LONG_URL = "https://example.test/" + "segment-without-any-break-opportunity/" * 6
# A code block keeps its line and scrolls inside itself; it must not widen the content column.
LONG_CODE_LINE = "long-code-line-" * 20

PAGE_RST = f"""About
=====

使用するルールブックは以下のとおりです。

:必須: トーキョーN◎VA THE AXLERATION 基本ルールブック
:必須: ジ・アザーサイド
:使用可: クロス・ザ・ライン

内容が複数のブロックを持つフィールドリスト。

:概要: 一段落目。

   二段落目。
:箇条書き:
   - 項目 A
   - 項目 B
:備考: 末尾の項目。

長い項目名と内容を持つフィールドリスト。

:{LONG_NAME}: {LONG_URL}
:コード例:
   .. code-block:: text

      {LONG_CODE_LINE}

通常の定義リスト。

用語
   通常の定義リストの説明。
"""

POST_RST = """:maatlog-post: true
:maatlog-slug: field-list
:maatlog-published-at: 2026-07-31T09:00:00Z

Field list post
===============

使用するルールブックは以下のとおりです。

:必須: トーキョーN◎VA THE AXLERATION 基本ルールブック
:必須: ジ・アザーサイド
:使用可: クロス・ザ・ライン
"""

FILES = {"about.rst": PAGE_RST, "post.rst": POST_RST}


class Box(TypedDict):
    left: float
    right: float
    top: float
    bottom: float
    width: float
    overflow: float


class FieldRow(TypedDict):
    name: str
    text: str
    dt: Box
    dd: Box | None
    blocks: list[Box]


class ListMetrics(TypedDict):
    dl: Box
    rows: list[FieldRow]


_MEASURE_JS = """(dl) => {
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      overflow: element.scrollWidth - element.clientWidth,
    };
  };
  const rows = [];
  for (const element of dl.children) {
    if (element.tagName === "DT") {
      rows.push({ name: element.innerText.trim(), text: "", dt: box(element), dd: null, blocks: [] });
    } else if (element.tagName === "DD" && rows.length > 0) {
      const row = rows[rows.length - 1];
      row.text = element.innerText;
      row.dd = box(element);
      row.blocks = [...element.children].map(box);
    }
  }
  return { dl: box(dl), rows };
}"""


def _measure(definition_list: Locator) -> ListMetrics:
    return cast(ListMetrics, definition_list.evaluate(_MEASURE_JS))


def _horizontal_overflow(page: Page) -> int:
    return cast(int, page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"))


def _assert_two_columns(metrics: ListMetrics, label: str) -> None:
    dl = metrics["dl"]
    rows = metrics["rows"]
    assert rows, label
    name_right = max(row["dt"]["right"] for row in rows)
    content_left = rows[0]["dd"]["left"] if rows[0]["dd"] is not None else None
    previous_bottom: float | None = None
    for row in rows:
        dt, dd, blocks = row["dt"], row["dd"], row["blocks"]
        where = f"{label} / {row['name']}: {row}"
        assert dd is not None and content_left is not None, where
        # 項目名は dl の左端から、内容は同じ行の上端から始まる。
        assert abs(dt["left"] - dl["left"]) <= TOLERANCE_PX, where
        assert abs(dd["top"] - dt["top"]) <= TOLERANCE_PX, where
        # 内容の列は項目名の列の右で揃い、40px の字下げは無い。
        assert abs(dd["left"] - content_left) <= TOLERANCE_PX, where
        assert name_right - TOLERANCE_PX <= dd["left"] <= name_right + MAX_COLUMN_GAP_PX, where
        # 長い項目名・内容は列の中で折り返す。
        assert dt["width"] <= dl["width"] * NAME_COLUMN_RATIO + TOLERANCE_PX, where
        assert dd["right"] <= dl["right"] + TOLERANCE_PX, where
        assert dt["overflow"] <= 0 and dd["overflow"] <= 0, where
        # 内容の先頭・末尾に段落の余白が残らず、ブロック同士は重ならない。
        assert blocks, where
        assert abs(blocks[0]["top"] - dd["top"]) <= TOLERANCE_PX, where
        assert abs(dd["bottom"] - blocks[-1]["bottom"]) <= TOLERANCE_PX, where
        for upper, lower in itertools.pairwise(blocks):
            assert lower["top"] >= upper["bottom"] - TOLERANCE_PX, where
        # 次の項目は前の内容の下から、間延びせずに始まる。
        if previous_bottom is not None:
            assert previous_bottom - TOLERANCE_PX <= dt["top"] <= previous_bottom + MAX_ROW_GAP_PX, where
        previous_bottom = max(dt["bottom"], dd["bottom"])


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_body_field_lists_render_as_two_columns(
    make_project: ProjectFactory, shared_browser: Browser, theme: str
) -> None:
    """Field names and contents share rows on normal pages and posts at desktop and phone widths."""
    result = make_project(files=FILES, theme=theme).build()
    for width, height in VIEWPORTS:
        page = shared_browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(result.path("about.html").resolve().as_uri(), wait_until="load")
            assert _horizontal_overflow(page) <= 0, (theme, width)
            field_lists = page.locator("section dl.field-list")
            assert field_lists.count() == 3
            simple, blocks, long = (_measure(field_lists.nth(index)) for index in range(3))
            for name, metrics in (("simple", simple), ("blocks", blocks), ("long", long)):
                _assert_two_columns(metrics, f"{theme} {width}px about {name}")
            assert [row["name"] for row in simple["rows"]] == ["必須:", "必須:", "使用可:"]
            assert [row["name"] for row in blocks["rows"]] == ["概要:", "箇条書き:", "備考:"]
            summary, bullets, _ = blocks["rows"]
            assert len(summary["blocks"]) == 2 and "二段落目。" in summary["text"]
            assert "項目 A" in bullets["text"] and "項目 B" in bullets["text"]
            assert LONG_URL in long["rows"][0]["text"]
            assert LONG_CODE_LINE in long["rows"][1]["text"]

            page.goto(result.path("post.html").resolve().as_uri(), wait_until="load")
            assert _horizontal_overflow(page) <= 0, (theme, width)
            post_lists = page.locator("section dl.field-list")
            assert post_lists.count() == 1
            _assert_two_columns(_measure(post_lists.first), f"{theme} {width}px post")
        finally:
            page.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_plain_definition_list_keeps_stacked_layout(
    make_project: ProjectFactory, shared_browser: Browser, theme: str
) -> None:
    """Only field lists change; an ordinary definition list still puts the description below the term."""
    result = make_project(files=FILES, theme=theme).build()
    page = shared_browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto(result.path("about.html").resolve().as_uri(), wait_until="load")
        plain = page.locator("section dl:not(.field-list)")
        assert plain.count() == 1
        (row,) = _measure(plain.first)["rows"]
        assert row["dd"] is not None, row
        assert row["dd"]["top"] >= row["dt"]["bottom"] - TOLERANCE_PX, row
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_field_lists_keep_theme_contrast(make_project: ProjectFactory, shared_browser: Browser, theme: str) -> None:
    """Field names and contents stay readable in both palettes."""
    result = make_project(files=FILES, theme=theme).build()
    for color_scheme in ("light", "dark"):
        context = shared_browser.new_context(color_scheme=color_scheme)
        try:
            page = context.new_page()
            for relative in ("about.html", "post.html"):
                page.goto(result.path(relative).resolve().as_uri(), wait_until="load")
                violations = [
                    item
                    for item in axe_violations(page, AXE_PATH, include="dl.field-list")
                    if item["id"] == "color-contrast"
                ]
                assert violations == [], (
                    f"{theme} {relative} ({color_scheme}): {json.dumps(violations, ensure_ascii=False, indent=2)}"
                )
        finally:
            context.close()

"""Issue #200 系の幅契約共有ヘルパ（#202 で作成。以降 B/C/D は読み取り専用）。

測定規則は Spec §4.6 C4（境界一致 2 CSS px 以内、document 横 overflow 1 CSS px 以下、
border-box の左右端を getBoundingClientRect で測る）に固定される。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from playwright.sync_api import Page

WIDTH_CONTRACT_PROJECT_ROOT = Path(__file__).resolve().parent / "width_contract"

#: AC8 の viewport 一覧（width, height）。
CONTRACT_VIEWPORTS: tuple[tuple[int, int], ...] = (
    (375, 812),
    (390, 844),
    (768, 1024),
    (769, 1024),
    (1024, 1366),
    (1025, 1366),
    (1280, 720),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
)

#: 境界の一致許容（CSS px）。
EDGE_TOLERANCE_PX = 2
#: document 横 overflow の許容（丸め誤差。CSS px）。
OVERFLOW_TOLERANCE_PX = 1

WRAPPER_SELECTOR = ".maatlog-table-wrapper"
#: % が解決される参照ボックス（Spec §4.6 C1）。
REFERENCE_BOX_POST = ".maatlog-post-body"
REFERENCE_BOX_NORMAL = ".maatlog-layout-page-normal .body"
#: コード外形（Spec §4.6 C3）。caption 付きは wrapper 全体、caption なしは .highlight-* div。
CODE_OUTER_CAPTIONED = ".literal-block-wrapper"
CODE_OUTER_PLAIN = "div[class*='highlight-']"


class ElementEdges(TypedDict):
    """border-box の左右端と幅（CSS px、Math.round 済み）。"""

    left: int
    right: int
    width: int


def measure_edges(page: Page, selector: str) -> ElementEdges | None:
    """``selector`` の最初の要素の border-box 左右端を返す（無ければ None）。"""
    return cast(
        "ElementEdges | None",
        page.evaluate(
            """(selector) => {
              const element = document.querySelector(selector);
              if (!element) return null;
              const box = element.getBoundingClientRect();
              return {
                left: Math.round(box.left),
                right: Math.round(box.right),
                width: Math.round(box.width),
              };
            }""",
            selector,
        ),
    )


def measure_reference_box(page: Page, selector: str) -> ElementEdges | None:
    """``selector`` の content box 左右端を返す（padding/border を明示的に差し引く）。"""
    return cast(
        "ElementEdges | None",
        page.evaluate(
            """(selector) => {
              const element = document.querySelector(selector);
              if (!element) return null;
              const box = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              const left = box.left
                + parseFloat(style.paddingLeft)
                + parseFloat(style.borderLeftWidth);
              const right = box.right
                - parseFloat(style.paddingRight)
                - parseFloat(style.borderRightWidth);
              return {
                left: Math.round(left),
                right: Math.round(right),
                width: Math.round(right - left),
              };
            }""",
            selector,
        ),
    )


def document_overflow(page: Page) -> int:
    """document の横 overflow（scrollWidth - clientWidth）。"""
    return cast(
        int,
        page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"),
    )


def element_exists(page: Page, selector: str) -> bool:
    return measure_edges(page, selector) is not None

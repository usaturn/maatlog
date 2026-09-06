"""Magazine acceptance fixture の定数とブラウザ検証ヘルパ。

既存 ``tests/acceptance/project`` は件数依存の期待値を持つため、Magazine の
検証記事はこの専用プロジェクトへ分離する（Issue #181）。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

from playwright.sync_api import Page

MAGAZINE_PROJECT_ROOT = Path(__file__).resolve().parent / "magazine_project"

#: 専用 Home のドキュメント名（``conf.py`` の ``maatlog_home_docname``）。
HOME_PAGE = "home.html"
#: Archive ルート（``conf.py`` の ``maatlog_archive_docname``）。
ARCHIVE_PAGE = "blog.html"

#: Issue #177 の viewport 表。``(width, height)``。
VIEWPORTS: tuple[tuple[int, int], ...] = (
    (3840, 2160),
    (2560, 1440),
    (1920, 1080),
    (1280, 720),
    (768, 1024),
    (390, 844),
)

#: 契約上 Latest が並ぶ列数（``width -> columns``）。
LATEST_COLUMNS: dict[int, int] = {3840: 3, 2560: 3, 1920: 3, 1280: 2, 768: 1, 390: 1}

#: ``maatlog_page_size``。専用 Home では Latest の上限を意味する。
PAGE_SIZE = 9

#: 公開記事の slug（新しい順）。``conf.py`` の記事群と一致させる。
PUBLISHED_SLUGS: tuple[str, ...] = (
    "mag-lead-en",
    "mag-second-ja",
    "mag-second-noimage",
    "mag-noexcerpt",
    "mag-long-ja-title",
    "mag-06",
    "mag-07",
    "mag-08",
    "mag-09",
    "mag-10",
    "mag-11",
    "mag-oldest",
)

#: 公開面に出てはならない slug。
UNPUBLISHED_SLUGS: tuple[str, ...] = ("mag-draft", "mag-scheduled", "mag-expired")


class CardBox(TypedDict):
    """1 枚のカードの位置・大きさ・variant。"""

    slug: str
    variant: str
    top: int
    left: int
    width: int
    height: int
    font_size: float


def card_boxes(page: Page, selector: str = ".maatlog-post-card") -> list[CardBox]:
    """*selector* に一致するカードを DOM 順で返す。"""
    return cast(
        list[CardBox],
        page.evaluate(
            """
            (selector) => Array.from(document.querySelectorAll(selector)).map((element) => {
              const rect = element.getBoundingClientRect();
              const title = element.querySelector('.maatlog-post-card-title');
              return {
                slug: element.dataset.slug ?? '',
                variant: element.dataset.maatlogCardVariant ?? '',
                top: Math.round(rect.top + window.scrollY),
                left: Math.round(rect.left + window.scrollX),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                font_size: title ? parseFloat(getComputedStyle(title).fontSize) : 0,
              };
            })
            """,
            selector,
        ),
    )


def horizontal_overflow(page: Page) -> int:
    """``documentElement`` の横はみ出し px。0 なら横スクロールなし。"""
    return cast(
        int,
        page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"),
    )


def row_widths(boxes: Sequence[CardBox], tolerance: int = 4) -> list[int]:
    """``top`` が *tolerance* px 以内で揃うカードを 1 行とみなし、行ごとの枚数を返す。"""
    rows: list[list[CardBox]] = []
    for box in sorted(boxes, key=lambda item: (item["top"], item["left"])):
        if rows and abs(rows[-1][0]["top"] - box["top"]) <= tolerance:
            rows[-1].append(box)
            continue
        rows.append([box])
    return [len(row) for row in rows]


FEATURED_VARIANTS: tuple[str, str, str] = ("lead", "secondary", "secondary")
LATEST_VARIANT = "latest"
PALETTES: tuple[str | None, ...] = (None, "github", "neon", "nord", "solarized")
LATEST_COLUMNS_EXACT: dict[int, int] = {1280: 2, 768: 1, 390: 1}
LATEST_COLUMNS_MIN: dict[int, int] = {3840: 3, 2560: 3, 1920: 3}


def featured_boxes(boxes: Sequence[CardBox]) -> list[CardBox]:
    """Featured（lead / secondary）のカードを DOM 順で返す。"""
    return [box for box in boxes if box["variant"] in {"lead", "secondary"}]


def latest_boxes(boxes: Sequence[CardBox]) -> list[CardBox]:
    """Latest のカードを DOM 順で返す。"""
    return [box for box in boxes if box["variant"] == LATEST_VARIANT]


def featured_is_one_plus_two(boxes: Sequence[CardBox], *, tolerance: int = 8) -> bool:
    """Wide の 1+2 bento（lead が左 2 行、secondary が右に 2 段）。"""
    if len(boxes) != 3:
        return False
    lead, first, second = boxes
    if lead["left"] + lead["width"] > first["left"] + tolerance:
        return False
    if abs(first["left"] - second["left"]) > tolerance:
        return False
    if abs(lead["top"] - first["top"]) > tolerance:
        return False
    if second["top"] <= first["top"]:
        return False
    return lead["height"] > first["height"]


def featured_is_stacked(boxes: Sequence[CardBox], *, tolerance: int = 8) -> bool:
    """Narrow の 1 列スタック。"""
    if len(boxes) != 3:
        return False
    lefts = [box["left"] for box in boxes]
    if max(lefts) - min(lefts) > tolerance:
        return False
    tops = [box["top"] for box in boxes]
    return tops == sorted(tops)

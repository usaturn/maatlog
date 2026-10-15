from __future__ import annotations

from pathlib import Path
from typing import TypedDict, cast

from playwright.sync_api import Page


class AxeNode(TypedDict):
    html: str
    target: list[str]


class AxeViolation(TypedDict):
    help: str
    id: str
    impact: str | None
    nodes: list[AxeNode]


def axe_violations(page: Page, axe_path: Path, *, include: str | None = None) -> list[AxeViolation]:
    """axe-core の違反を返す。``include`` は検査を CSS セレクタに当たる要素の下に限る。既定は文書全体。"""
    if not axe_path.is_file():
        raise AssertionError(f"axe-core script missing: {axe_path}; run `npm ci`")
    page.add_script_tag(path=str(axe_path))
    result = page.evaluate(
        """
        async (include) => {
          const { violations } = await axe.run(include ?? document, { resultTypes: ["violations"] });
          return violations.map(({ help, id, impact, nodes }) => ({
            help,
            id,
            impact,
            nodes: nodes.map(({ html, target }) => ({ html, target })),
          }));
        }
        """,
        include,
    )
    return cast(list[AxeViolation], result)

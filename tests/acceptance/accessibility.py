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


def axe_violations(page: Page, axe_path: Path) -> list[AxeViolation]:
    if not axe_path.is_file():
        raise AssertionError(f"axe-core script missing: {axe_path}; run `npm ci`")
    page.add_script_tag(path=str(axe_path))
    result = page.evaluate(
        """
        async () => {
          const { violations } = await axe.run(document, { resultTypes: ["violations"] });
          return violations.map(({ help, id, impact, nodes }) => ({
            help,
            id,
            impact,
            nodes: nodes.map(({ html, target }) => ({ html, target })),
          }));
        }
        """
    )
    return cast(list[AxeViolation], result)

"""Integration tests for the MaatLog page shell (banner / 3-column layout)."""

from __future__ import annotations

import pytest
from conftest import ProjectFactory

LAYOUT_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: hello
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
---
# Hello

## Section A

First section body.

## Section B

Second section body.
""",
    "about.rst": "About\n=====\n\nA plain page that is not a post.\n",
}

SHELL_PAGES = ("index.html", "about.html", "post.html", "blog.html")

RELATED_BAR_PAGES = (
    "index.html",
    "about.html",
    "post.html",
    "blog.html",
    "blog/tag/sphinx.html",
    "blog/category/engineering.html",
    "blog/author/alice.html",
    "blog/month/2026-07.html",
    "search.html",
    "genindex.html",
)


@pytest.mark.parametrize("page_name", SHELL_PAGES)
def test_shell_is_present_on_every_page(make_project: ProjectFactory, page_name: str) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html(page_name)

    assert page.select_one(".maatlog-layout[data-maatlog-component='layout']")
    assert page.select_one("main.maatlog-layout-main")
    assert page.select_one(".maatlog-skip-link")


def test_no_sphinx_related_bar_remains(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()

    for page_name in RELATED_BAR_PAGES:
        related_count = len(result.html(page_name).select("div.related"))
        assert related_count == 0, f"{page_name} still contains {related_count} Sphinx related bar(s)"


def test_basic_body_wrappers_are_preserved(make_project: ProjectFactory) -> None:
    # basic.css / sphinx-copybutton / 利用者の custom.css がこの入れ子に依存している。
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-layout-main .documentwrapper .bodywrapper .body")
    assert page.select_one(".maatlog-layout-main .body .maatlog-post")


def test_skip_link_targets_the_main_element(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    skip = page.select_one(".maatlog-skip-link")
    main = page.select_one("main.maatlog-layout-main")
    assert skip is not None and main is not None
    assert skip["href"] == "#maatlog-main"
    assert main["id"] == "maatlog-main"
    assert page.text.index('class="maatlog-skip-link"') < page.text.index('class="maatlog-banner"')


def test_base_theme_gets_the_same_shell(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-base").build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-layout[data-maatlog-component='layout']")
    assert len(page.select("div.related")) == 0

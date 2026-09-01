"""Integration tests for the MaatLog page shell (banner / responsive layout)."""

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

CHILD_LAYOUT_OPT_IN = """\
{%- extends "!layout.html" -%}
{%- set maatlog_has_toc = True -%}
{%- block maatlog_toc -%}
<aside class="maatlog-toc" data-maatlog-component="toc">
<p>Custom TOC</p>
</aside>
{%- endblock maatlog_toc -%}
"""


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
    assert page.select_one(".maatlog-layout.maatlog-layout-has-toc")
    assert len(page.select("div.related")) == 0


@pytest.mark.parametrize(
    ("page_name", "expected"),
    [
        # 見出しが2つある投稿ページ / 投稿カードを持つアーカイブ → TOC あり
        ("post.html", True),
        ("blog.html", True),
        # 見出し1つだけの通常ページ → TOC なし
        ("about.html", False),
    ],
)
def test_layout_marks_only_pages_that_render_a_toc(
    make_project: ProjectFactory, page_name: str, expected: bool
) -> None:
    # 空の TOC トラックを作らないため、レイアウトは TOC の有無を状態クラスで公開する。
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html(page_name)

    assert (page.select_one(".maatlog-layout.maatlog-layout-has-toc") is not None) is expected
    assert (page.select_one(".maatlog-toc") is not None) is expected


def test_child_layout_can_opt_in_to_toc_state(make_project: ProjectFactory) -> None:
    # 派生テンプレートが root-level で maatlog_has_toc を明示し、標準より広い
    # 条件で maatlog_toc を出せば、状態クラスと aside は両方存在する。
    files = {
        **LAYOUT_PROJECT,
        "_templates/layout.html": CHILD_LAYOUT_OPT_IN,
    }
    page = (
        make_project(
            files=files,
            theme="maatlog-default",
            config={"templates_path": ["_templates"]},
        )
        .build()
        .html("about.html")
    )

    assert page.select_one(".maatlog-toc") is not None
    assert page.select_one(".maatlog-layout.maatlog-layout-has-toc") is not None


@pytest.mark.parametrize(
    ("page_name", "page_kind"),
    [
        ("index.html", "normal"),
        ("about.html", "normal"),
        ("post.html", "post"),
        ("blog.html", "archive"),
    ],
)
def test_layout_exposes_the_page_kind_as_a_state_class(
    make_project: ProjectFactory, page_name: str, page_kind: str
) -> None:
    page = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build().html(page_name)

    assert page.select_one(f".maatlog-layout.maatlog-layout-page-{page_kind}") is not None


def test_home_layout_exposes_the_home_page_kind(make_project: ProjectFactory) -> None:
    page = (
        make_project(
            files=LAYOUT_PROJECT,
            theme="maatlog-default",
            config={"maatlog_home_docname": "index"},
        )
        .build()
        .html("index.html")
    )

    assert page.select_one(".maatlog-layout.maatlog-layout-page-home") is not None

"""Integration tests for the right-hand table of contents sidebar."""

from __future__ import annotations

import pytest
from fixtures.integration_builds import BuiltProjects

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
    "about.rst": "About\n=====\n\nA plain page with a single heading.\n",
}


@pytest.mark.xdist_group("integration-toc-default")
def test_post_cards_carry_anchor_ids(built_projects: BuiltProjects) -> None:
    result = built_projects.project(files=LAYOUT_PROJECT, theme="maatlog-default")
    page = result.html("blog.html")

    card = page.select_one(".maatlog-post-card[data-slug='hello']")
    assert card is not None
    assert card["id"] == "maatlog-post-hello"


@pytest.mark.xdist_group("integration-toc-default")
def test_post_page_shows_its_headings(built_projects: BuiltProjects) -> None:
    result = built_projects.project(files=LAYOUT_PROJECT, theme="maatlog-default")
    page = result.html("post.html")

    assert page.select_one(".maatlog-toc[data-maatlog-component='toc']")
    hrefs = [item.get("href", "") for item in page.select(".maatlog-toc-headings a")]
    assert "#section-a" in hrefs
    assert "#section-b" in hrefs


@pytest.mark.xdist_group("integration-toc-default")
def test_single_heading_page_has_no_toc_sidebar(built_projects: BuiltProjects) -> None:
    result = built_projects.project(files=LAYOUT_PROJECT, theme="maatlog-default")
    page = result.html("about.html")

    assert page.select_one(".maatlog-toc") is None


@pytest.mark.xdist_group("integration-toc-default")
def test_archive_page_links_to_the_cards_on_that_page(built_projects: BuiltProjects) -> None:
    result = built_projects.project(files=LAYOUT_PROJECT, theme="maatlog-default")
    page = result.html("blog.html")

    hrefs = [item.get("href", "") for item in page.select(".maatlog-toc-posts a")]
    assert hrefs == ["#maatlog-post-hello"]


def test_home_page_links_to_the_cards_on_that_page(built_projects: BuiltProjects) -> None:
    result = built_projects.project(
        files=LAYOUT_PROJECT,
        theme="maatlog-default",
        config={"maatlog_home_docname": "index"},
    )
    page = result.html("index.html")

    hrefs = [item.get("href", "") for item in page.select(".maatlog-toc-posts a")]
    assert hrefs == ["#maatlog-post-hello"]


def test_home_post_list_does_not_duplicate_card_anchor(built_projects: BuiltProjects) -> None:
    files = {
        "index.rst": """Home
====

.. maatlog:post-list::

.. toctree::
   :hidden:

   post
""",
        "post.md": LAYOUT_PROJECT["post.md"],
    }
    page = built_projects.project(
        files=files,
        theme="maatlog-default",
        config={"maatlog_home_docname": "index"},
    ).html("index.html")

    cards = page.select('.maatlog-post-card[data-slug="hello"]')
    assert len(cards) == 2
    assert [card.get("id") for card in cards].count("maatlog-post-hello") == 1
    assert [item.get("href") for item in page.select(".maatlog-toc-posts a")] == ["#maatlog-post-hello"]


def test_toc_sidebar_is_absent_without_posts_or_headings(built_projects: BuiltProjects) -> None:
    result = built_projects.project(
        files={"about.rst": "About\n=====\n\nNo posts, one heading.\n"}, theme="maatlog-default"
    )
    page = result.html("about.html")

    assert page.select_one(".maatlog-toc") is None
    assert page.select_one(".maatlog-layout-has-toc") is None


@pytest.mark.xdist_group("integration-toc-default")
def test_state_class_matches_the_rendered_rail(built_projects: BuiltProjects) -> None:
    # 状態クラスと実際の right rail がずれると、空の列や欠けた列が生まれる。
    result = built_projects.project(files=LAYOUT_PROJECT, theme="maatlog-default")
    for page_name in ("post.html", "about.html", "blog.html"):
        page = result.html(page_name)
        has_rail_element = page.select_one(".maatlog-right-rail") is not None
        has_state = page.select_one(".maatlog-layout-has-rail") is not None
        assert has_rail_element == has_state, page_name

"""Integration tests for the right-hand table of contents sidebar."""

from __future__ import annotations

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
    "about.rst": "About\n=====\n\nA plain page with a single heading.\n",
}


def test_post_cards_carry_anchor_ids(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("blog.html")

    card = page.select_one(".maatlog-post-card[data-slug='hello']")
    assert card is not None
    assert card["id"] == "maatlog-post-hello"


def test_post_page_shows_its_headings(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-toc[data-maatlog-component='toc']")
    hrefs = [item.get("href", "") for item in page.select(".maatlog-toc-headings a")]
    assert "#section-a" in hrefs
    assert "#section-b" in hrefs


def test_single_heading_page_has_no_toc_sidebar(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-toc") is None


def test_archive_page_links_to_the_cards_on_that_page(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("blog.html")

    hrefs = [item.get("href", "") for item in page.select(".maatlog-toc-posts a")]
    assert hrefs == ["#maatlog-post-hello"]


def test_home_page_links_to_the_cards_on_that_page(make_project: ProjectFactory) -> None:
    result = make_project(
        files=LAYOUT_PROJECT,
        theme="maatlog-default",
        config={"maatlog_home_docname": "index"},
    ).build()
    page = result.html("index.html")

    hrefs = [item.get("href", "") for item in page.select(".maatlog-toc-posts a")]
    assert hrefs == ["#maatlog-post-hello"]


def test_home_post_list_does_not_duplicate_card_anchor(make_project: ProjectFactory) -> None:
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
    page = (
        make_project(
            files=files,
            theme="maatlog-default",
            config={"maatlog_home_docname": "index"},
        )
        .build()
        .html("index.html")
    )

    cards = page.select('.maatlog-post-card[data-slug="hello"]')
    assert len(cards) == 2
    assert [card.get("id") for card in cards].count("maatlog-post-hello") == 1
    assert [item.get("href") for item in page.select(".maatlog-toc-posts a")] == ["#maatlog-post-hello"]


def test_toc_sidebar_is_absent_without_posts_or_headings(make_project: ProjectFactory) -> None:
    result = make_project(
        files={"about.rst": "About\n=====\n\nNo posts, one heading.\n"}, theme="maatlog-default"
    ).build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-toc") is None

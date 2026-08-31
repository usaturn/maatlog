"""Integration tests for the header banner and the left navigation sidebar."""

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
""",
    "about.rst": "About\n=====\n\nA plain page that is not a post.\n",
}

BANNER_PAGES = ("index.html", "about.html", "post.html", "blog.html")


@pytest.mark.parametrize("page_name", BANNER_PAGES)
def test_banner_is_on_every_page(make_project: ProjectFactory, page_name: str) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html(page_name)

    assert page.select_one(".maatlog-banner[data-maatlog-component='banner']")
    assert page.select_one(".maatlog-banner .maatlog-banner-title")
    assert page.select_one(".maatlog-banner .maatlog-banner-search")


def test_banner_shows_the_tagline_when_configured(make_project: ProjectFactory) -> None:
    result = make_project(
        files=LAYOUT_PROJECT,
        theme="maatlog-default",
        config={"maatlog_tagline": "Notes on Sphinx"},
    ).build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-banner-tagline")
    assert "Notes on Sphinx" in page


def test_banner_omits_the_tagline_when_unset(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-banner-tagline") is None


def test_banner_omits_the_logo_when_html_logo_is_unset(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-banner-logo") is None
    assert page.select_one(".maatlog-banner-title")


def test_banner_title_links_to_the_root_document(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    link = page.select_one(".maatlog-banner-title a")
    assert link is not None
    assert link["href"] in {"index.html", "#"}


NAV_PAGES = ("index.html", "about.html", "post.html", "blog.html")


@pytest.mark.parametrize("page_name", NAV_PAGES)
def test_left_nav_is_on_every_page(make_project: ProjectFactory, page_name: str) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html(page_name)

    assert page.select_one(".maatlog-layout .maatlog-nav[data-maatlog-component='nav']")


def test_left_nav_carries_the_site_toctree(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    hrefs = [item.get("href", "") for item in page.select(".maatlog-nav-toctree a")]
    assert any(href.endswith("post.html") for href in hrefs)


def test_left_nav_carries_taxonomies_on_a_plain_page(make_project: ProjectFactory) -> None:
    # Theme API 1.2: 投稿でないページでもタクソノミーが渡る。
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-nav .maatlog-sidebar[data-maatlog-component='sidebar']")
    hrefs = [item.get("href", "") for item in page.select(".maatlog-nav .maatlog-taxonomy a")]
    assert any(href.endswith("blog/tag/sphinx.html") for href in hrefs)


def test_left_nav_excludes_hidden_toctrees(make_project: ProjectFactory) -> None:
    files = {
        "index.rst": """Root
====

.. toctree::

   about

.. toctree::
   :hidden:

   hidden-post
   draft
""",
        "about.rst": "About\n=====\n",
        "hidden-post.rst": (
            ":maatlog-post: true\n:maatlog-slug: hidden\n:maatlog-published-at: 2026-07-01T00:00:00Z\n"
            "\nHidden Post\n===========\n"
        ),
        "draft.rst": ":maatlog-post: true\n:maatlog-slug: draft\n\nDraft Secret\n============\n",
    }
    page = make_project(files=files, theme="maatlog-default").build().html("index.html")

    assert page.select_one(".maatlog-nav-toctree")
    assert any(item.get("href", "").endswith("about.html") for item in page.select(".maatlog-nav-toctree a"))
    assert "Hidden Post" not in page.text
    assert "Draft Secret" not in page.text


def test_left_nav_uses_one_navigation_landmark(make_project: ProjectFactory) -> None:
    page = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build().html("about.html")

    assert len(page.select("nav.maatlog-nav")) == 1
    assert page.select_one("nav.maatlog-nav div.maatlog-sidebar")
    assert page.select_one("nav.maatlog-nav aside.maatlog-sidebar") is None


@pytest.mark.parametrize("page_name", NAV_PAGES)
def test_sidebar_is_never_rendered_inside_the_body(make_project: ProjectFactory, page_name: str) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    page = result.html(page_name)

    assert page.select(".maatlog-layout-main .maatlog-sidebar") == []


def test_left_nav_has_no_empty_taxonomy_sections_without_posts(make_project: ProjectFactory) -> None:
    result = make_project(files={"about.rst": "About\n=====\n\nNo posts here.\n"}, theme="maatlog-default").build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-nav")
    assert page.select(".maatlog-taxonomy") == []


def test_base_theme_gets_the_same_left_nav(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-base").build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-nav .maatlog-sidebar")
    assert page.select(".maatlog-layout-main .maatlog-sidebar") == []

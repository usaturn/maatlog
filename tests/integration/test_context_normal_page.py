"""The maatlog namespace on pages that are neither post, archive, nor home."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import ProjectFactory

from maatlog.extension import inject_maatlog_page_context

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


def _context_for(make_project: ProjectFactory, pagename: str) -> dict[str, Any]:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    context: dict[str, Any] = {}
    inject_maatlog_page_context(result.app, pagename, "page.html", context, None)
    return context


def test_normal_page_gets_taxonomy_navigation(make_project: ProjectFactory) -> None:
    context = _context_for(make_project, "about")
    maatlog = context["maatlog"]

    assert maatlog["page_kind"] == "normal"
    assert maatlog["post"] is None
    assert [item["id"] for item in maatlog["taxonomies"]["tags"]] == ["sphinx"]
    assert [item["id"] for item in maatlog["taxonomies"]["categories"]] == ["engineering"]
    assert [item["id"] for item in maatlog["taxonomies"]["authors"]] == ["alice"]
    assert maatlog["taxonomies"]["months"]


def test_normal_page_taxonomy_urls_are_relative_to_that_page(make_project: ProjectFactory) -> None:
    context = _context_for(make_project, "about")
    tags = context["maatlog"]["taxonomies"]["tags"]

    assert tags[0]["url"].endswith("blog/tag/sphinx.html")


def test_normal_page_gets_site_and_feeds(make_project: ProjectFactory) -> None:
    context = _context_for(make_project, "about")
    maatlog = context["maatlog"]

    assert maatlog["site"]["title"]
    assert maatlog["feeds"]


def test_preseeded_context_is_not_recomputed(
    make_project: ProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    context: dict[str, Any] = {"maatlog": {"page_kind": "archive"}}

    def fail_if_called(**_kwargs: object) -> object:
        raise AssertionError("normal_page_context must stay lazy for preseeded pages")

    monkeypatch.setattr("maatlog.extension.normal_page_context", fail_if_called)
    inject_maatlog_page_context(result.app, "blog", "maatlog/archive.html", context, None)

    assert context["maatlog"] == {"page_kind": "archive"}


def test_project_without_posts_gets_empty_navigation(make_project: ProjectFactory) -> None:
    result = make_project(files={"about.rst": "About\n=====\n\nNo posts here.\n"}, theme="maatlog-default").build()
    context: dict[str, Any] = {}

    inject_maatlog_page_context(result.app, "about", "page.html", context, None)

    assert context["maatlog"]["taxonomies"]["tags"] == ()
    assert context["maatlog"]["page_kind"] == "normal"


def test_normal_page_has_an_author_summaries_key(make_project: ProjectFactory) -> None:
    maatlog = _context_for(make_project, "about")["maatlog"]

    assert "author_summaries" in maatlog

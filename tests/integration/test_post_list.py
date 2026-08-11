"""Integration tests for ``maatlog:post-list`` and post navigation wiring."""

from __future__ import annotations

import re

import pytest
from conftest import ProjectFactory, SphinxFactory

from maatlog.errors import MaatlogBuildError

# SOURCE_DATE_EPOCH default is 2026-08-01T00:00:00Z
POST_LIST_PROJECT = {
    "index.rst": """\
Root
====

.. maatlog:post-list::
   :tags: sphinx, python
   :authors: alice
   :limit: 2

.. toctree::
   :hidden:

   first
   second
   third
   draft
   other-author
""",
    "first.md": """---
maatlog-post: true
maatlog-slug: first
maatlog-published-at: 2026-07-31T12:00:00Z
maatlog-tags: [sphinx]
maatlog-authors: [alice]
---
# First

First post.
""",
    "second.md": """---
maatlog-post: true
maatlog-slug: second
maatlog-published-at: 2026-07-30T12:00:00Z
maatlog-tags: [python]
maatlog-authors: [alice]
---
# Second

Second post.
""",
    "third.md": """---
maatlog-post: true
maatlog-slug: third
maatlog-published-at: 2026-07-29T12:00:00Z
maatlog-tags: [sphinx]
maatlog-authors: [alice]
---
# Third

Third post (limit excludes this).
""",
    "draft.md": """---
maatlog-post: true
maatlog-slug: draft
maatlog-tags: [sphinx]
maatlog-authors: [alice]
---
# Draft

Unpublished.
""",
    "other-author.md": """---
maatlog-post: true
maatlog-slug: other-author
maatlog-published-at: 2026-07-28T12:00:00Z
maatlog-tags: [sphinx]
maatlog-authors: [bob]
---
# Other Author

Different author axis (AND excludes this).
""",
}


def test_post_list_filters_and_limits(make_project: ProjectFactory) -> None:
    result = make_project(files=POST_LIST_PROJECT, builder="html").build()
    cards = result.html("index.html").select(".maatlog-post-list .maatlog-post-card")
    assert [card["data-slug"] for card in cards] == ["first", "second"]


def test_post_list_empty_renders_empty_component(make_project: ProjectFactory) -> None:
    files = {
        "index.rst": """\
Root
====

.. maatlog:post-list::
   :tags: missing

.. toctree::
   :hidden:

   only
   draft
""",
        "only.md": """---
maatlog-post: true
maatlog-slug: only
maatlog-published-at: 2026-07-01T00:00:00Z
maatlog-tags: [present]
---
# Only
""",
        "draft.md": """---
maatlog-post: true
maatlog-slug: draft-secret
maatlog-tags: [missing]
---
# Draft Secret Title
""",
    }
    result = make_project(files=files, builder="html").build()
    page = result.html("index.html")
    assert page.select_one(".maatlog-post-list") is not None
    assert page.select(".maatlog-post-list .maatlog-post-card") == []
    # Empty list must not disclose unpublished posts (draft matches the filter tag).
    lower = page.text.lower()
    assert "draft secret" not in lower
    assert "draft-secret" not in lower
    assert "unpublished" not in lower


def test_post_list_non_html_bullet_list(make_project: ProjectFactory) -> None:
    result = make_project(files=POST_LIST_PROJECT, builder="text").build()
    text = result.path("index.txt").read_text(encoding="utf-8")
    # first and second titles only (limit 2); draft/other-author absent from list region.
    assert "First" in text
    assert "Second" in text
    # third matches filter but is beyond limit
    # Count title occurrences carefully — "Third" should not appear as a list entry near top.
    assert re.search(r"^\*\s+First", text, re.MULTILINE)
    assert re.search(r"^\*\s+Second", text, re.MULTILINE)
    assert not re.search(r"^\*\s+Third", text, re.MULTILINE)
    assert not re.search(r"^\*\s+Draft", text, re.MULTILINE)


def test_post_list_non_html_internal_titles_are_references(make_sphinx: SphinxFactory) -> None:
    """Non-HTML post-list items must be concrete references (not late pending_xref)."""
    from docutils import nodes
    from sphinx import addnodes

    app = make_sphinx(files=POST_LIST_PROJECT, builder="text")
    app.build()
    doctree = app.env.get_and_resolve_doctree("index", app.builder, tags=app.builder.tags)

    for title in ("First", "Second"):
        refs = [n for n in doctree.findall(nodes.reference) if n.astext() == title]
        assert refs, f"{title!r} must appear as nodes.reference after non-HTML projection"
        assert all(ref.get("internal") or ref.get("refuri") for ref in refs)

    pending_post = [
        n
        for n in doctree.findall(addnodes.pending_xref)
        if n.get("refdomain") == "maatlog" and n.get("reftarget") in {"first", "second"}
    ]
    assert not pending_post, "post-list must not leave unresolved pending_xref for listed posts"


def test_post_list_unknown_option_fails(make_sphinx: SphinxFactory) -> None:
    files = {
        "index.rst": """\
Root
====

.. maatlog:post-list::
   :unknown: x
""",
    }
    app = make_sphinx(files=files)
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.archive.option-invalid"
    assert diagnostic.field == "unknown"
    assert diagnostic.line is not None


@pytest.mark.parametrize(
    ("option_block", "code", "field"),
    [
        (":tags:\n", "maatlog.archive.option-invalid", "tags"),
        (":tags: Not_Valid\n", "maatlog.archive.option-invalid", "tags"),
        (":month: 2026-13\n", "maatlog.archive.option-invalid", "month"),
        (":limit: 0\n", "maatlog.archive.option-invalid", "limit"),
        (":limit: no\n", "maatlog.archive.option-invalid", "limit"),
    ],
)
def test_post_list_invalid_options(
    make_sphinx: SphinxFactory,
    option_block: str,
    code: str,
    field: str,
) -> None:
    body = f"""\
Root
====

.. maatlog:post-list::
   {option_block}
"""
    app = make_sphinx(files={"index.rst": body})
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.field == field
    assert diagnostic.source is not None
    assert diagnostic.line is not None


def test_post_list_undefined_allowlist_id(make_sphinx: SphinxFactory) -> None:
    body = """\
Root
====

.. maatlog:post-list::
   :tags: unknown
"""
    app = make_sphinx(
        files={"index.rst": body},
        config={"maatlog_tags": {"sphinx": "Sphinx"}},
    )
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.archive.filter-undefined"
    assert diagnostic.field == "tags"
    assert diagnostic.message == "Undefined tag ID in post-list"
    assert diagnostic.line is not None


def test_post_list_undefined_category_message_uses_singular(make_sphinx: SphinxFactory) -> None:
    body = """\
Root
====

.. maatlog:post-list::
   :categories: missing
"""
    app = make_sphinx(
        files={"index.rst": body},
        config={"maatlog_categories": {"engineering": "Engineering"}},
    )
    with pytest.raises(MaatlogBuildError) as error:
        app.build()
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.archive.filter-undefined"
    assert diagnostic.field == "categories"
    assert diagnostic.message == "Undefined category ID in post-list"
    assert "categorie" not in diagnostic.message


def test_post_page_has_neighbors_and_sidebar(make_project: ProjectFactory) -> None:
    files = {
        "newer.md": """---
maatlog-post: true
maatlog-slug: newer
maatlog-published-at: 2026-07-03T00:00:00Z
maatlog-tags: [alpha]
---
# Newer
""",
        "middle.md": """---
maatlog-post: true
maatlog-slug: middle
maatlog-published-at: 2026-07-02T00:00:00Z
maatlog-tags: [beta]
---
# Middle
""",
        "older.md": """---
maatlog-post: true
maatlog-slug: older
maatlog-published-at: 2026-07-01T00:00:00Z
maatlog-tags: [alpha]
---
# Older
""",
    }
    result = make_project(files=files, builder="html").build()
    page = result.html("middle.html")
    assert page.select_one(".maatlog-nav-newer") is not None
    assert page.select_one(".maatlog-nav-older") is not None
    assert "Newer" in page.text
    assert "Older" in page.text
    # Sidebar taxonomy from published posts only
    assert page.select_one(".maatlog-taxonomy-tags") is not None
    assert "alpha" in page.text
    assert "beta" in page.text


def test_archive_sidebar_has_taxonomies(make_project: ProjectFactory) -> None:
    files = {
        "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-10T00:00:00Z
maatlog-tags: [sphinx]
maatlog-authors: [alice]
---
# One
""",
    }
    result = make_project(files=files, builder="html").build()
    archive = result.html("blog.html")
    assert archive.select_one(".maatlog-sidebar") is not None
    assert archive.select_one(".maatlog-taxonomy-tags") is not None
    assert archive.select_one(".maatlog-taxonomy-authors") is not None
    assert archive.select_one(".maatlog-taxonomy-months") is not None

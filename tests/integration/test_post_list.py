"""Integration tests for ``maatlog:post-list`` and post navigation wiring."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import pytest
from conftest import ProjectFactory, SphinxFactory
from sphinx.application import Sphinx

from maatlog.errors import MaatlogBuildError

# SOURCE_DATE_EPOCH default is 2026-08-01T00:00:00Z — publish before that.
MULTIPAGE_PROJECT = {
    "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
---
# One

First sphinx post.
""",
    "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
---
# Two

Second sphinx post.
""",
    "three.md": """---
maatlog-post: true
maatlog-slug: three
maatlog-published-at: 2026-07-29T09:00:00Z
maatlog-tags: [python]
maatlog-authors: [bob]
---
# Three

Non-sphinx post for pagination contrast.
""",
}

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
    # Empty list must not disclose unpublished posts, neither as listing cards
    # nor as a title anywhere on the page (draft matches the filter tag).
    assert page.select('.maatlog-post-card[data-slug="draft-secret"]') == []
    lower = page.text.lower()
    assert "draft-secret" not in lower
    assert "draft secret" not in lower
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


def test_post_list_cards_are_not_fallback_markup(make_project: ProjectFactory) -> None:
    """post-list renders the theme card, not the minimal fallback markup.

    ``_render_post_card`` swallows template errors and degrades to a
    title-only card. Asserting on the date proves the real template ran.
    """
    files = dict(MULTIPAGE_PROJECT)
    files["index.rst"] = (
        "Home\n====\n\n.. maatlog:post-list::\n\n.. toctree::\n   :hidden:\n\n   one\n   two\n   three\n"
    )
    result = make_project(files=files).build()
    page = result.html("index.html")

    assert page.select_one(".maatlog-post-list .maatlog-post-card") is not None
    assert page.select_one("time.maatlog-post-card-date") is not None


TAXONOMY_POST_LIST_PROJECT = {
    "index.rst": "Home\n====\n\n.. maatlog:post-list::\n",
    "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: An excerpt.
---
# One

First post.
""",
}


def test_post_list_cards_expose_taxonomy_links(make_project: ProjectFactory) -> None:
    """Cards rendered through the directive must not fall back to minimal markup."""
    result = make_project(files=TAXONOMY_POST_LIST_PROJECT).build()
    page = result.html("index.html")
    # Fallback markup has no date and no excerpt — assert the full card is rendered.
    assert page.select_one(".maatlog-post-card-date") is not None
    assert page.select_one(".maatlog-post-card-excerpt") is not None
    assert page.select_one(".maatlog-post-card [href='blog/tag/sphinx.html']") is not None
    assert page.select_one(".maatlog-post-card [href='blog/category/engineering.html']") is not None
    assert page.select_one(".maatlog-post-card [href='blog/author/alice.html']") is not None


def test_post_card_render_failure_warns_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken post-card template warns instead of degrading silently."""
    srcdir = tmp_path / "source"
    theme_dir = srcdir / "_themes" / "broken"
    (theme_dir / "maatlog" / "components").mkdir(parents=True)
    (theme_dir / "maatlog-theme.toml").write_text(
        '[maatlog]\napi = "1.0"\nimplementation = "inherits-base"\n', encoding="utf-8"
    )
    (theme_dir / "theme.conf").write_text(
        "[theme]\ninherit = maatlog-base\nstylesheet = maatlog.css\n", encoding="utf-8"
    )
    # Raises inside Jinja at render time; ``card`` has no ``does_not_exist``.
    (theme_dir / "maatlog" / "components" / "post-card.html").write_text(
        "{{ card.does_not_exist.boom }}", encoding="utf-8"
    )
    for name, content in TAXONOMY_POST_LIST_PROJECT.items():
        (srcdir / name).write_text(content, encoding="utf-8")
    (srcdir / "conf.py").write_text(
        "\n".join(
            [
                "extensions = ['maatlog']",
                "source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}",
                "root_doc = 'index'",
                "html_baseurl = 'https://example.test/'",
                "html_theme_path = ['_themes']",
                "html_theme = 'broken'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785542400")

    # Archive pages {% include %} the same post-card template; skip them so this
    # test only exercises ``_render_post_card`` (the visitor catch path).
    def skip_archive_pages(_app: Sphinx) -> list[tuple[str, dict[str, object], str]]:
        return []

    monkeypatch.setattr("maatlog.extension.collect_archive_pages", skip_archive_pages)
    warning_stream = StringIO()
    app = Sphinx(
        str(srcdir),
        str(srcdir),
        str(tmp_path / "output"),
        str(tmp_path / "doctrees"),
        "html",
        status=StringIO(),
        warning=warning_stream,
        warningiserror=False,
        freshenv=True,
    )
    app.__dict__["_maatlog_test_warning_stream"] = warning_stream
    app.build()

    warnings = warning_stream.getvalue()
    assert "theme.post-card-render-failed" in warnings
    # Warned once, not once per card.
    assert warnings.count("theme.post-card-render-failed") == 1
    html = (Path(app.outdir) / "index.html").read_text(encoding="utf-8")
    assert 'class="maatlog-post-card"' in html


@pytest.mark.parametrize("feeds", [False, True], ids=["feeds-off", "feeds-on"])
def test_post_list_page_rewritten_when_scheduled_post_publishes(make_project: ProjectFactory, feeds: bool) -> None:
    """Issue #32: post-list pages must follow publication changes incrementally.

    The listing page must not be the scheduled post's direct toctree parent
    (``nav.rst`` is): Sphinx rewrites direct toctree parents of changed docs
    via ``files_to_rebuild``, which would mask a missing ``env-get-updated``
    entry for the listing page itself.
    """
    files = {
        "listing.rst": "Posts\n=====\n\n.. maatlog:post-list::\n",
        "nav.rst": "Nav\n===\n\n.. toctree::\n\n   scheduled\n",
        "scheduled.md": """---
maatlog-post: true
maatlog-slug: future-post
maatlog-published-at: 2026-08-01T12:00:00Z
maatlog-tags: [secret]
---
# Future Post

Scheduled body.
""",
    }
    project = make_project(
        files=files,
        source_date_epoch="1782864000",  # 2026-07-01 — before publication
        config={"maatlog_generate_feeds": feeds, "maatlog_timezone": "UTC"},
    )
    first = project.build(reuse_environment=False)
    first_page = first.html("listing.html")
    assert first_page.select(".maatlog-post-list .maatlog-post-card") == []
    assert not first.path("blog/tag/secret.html").exists()

    project.source_date_epoch = "1786752000"  # 2026-08-15 — after publication
    second = project.build(reuse_environment=True)
    second_page = second.html("listing.html")
    assert second_page.select(".maatlog-post-list .maatlog-post-card") != []
    assert second_page.select_one(".maatlog-post-card [href='blog/tag/secret.html']") is not None
    assert second.path("blog/tag/secret.html").exists()

from __future__ import annotations

import re
from pathlib import Path

from conftest import SphinxFactory
from docutils import nodes
from sphinx.application import Sphinx

from maatlog.config import TaxonomyAxis
from maatlog.domain import MaatlogDomain
from maatlog.references import archive_docname


def _rst_post(
    *,
    slug: str,
    title: str,
    published_at: str | None = "2026-07-15T12:00:00Z",
    tags: str = "sphinx",
    categories: str = "engineering",
    authors: str = "alice",
    body: str = "",
) -> str:
    lines = [
        ":maatlog-post: true",
        f":maatlog-slug: {slug}",
    ]
    if published_at is not None:
        lines.append(f":maatlog-published-at: {published_at}")
    if tags:
        lines.append(f":maatlog-tags: {tags}")
    if categories:
        lines.append(f":maatlog-categories: {categories}")
    if authors:
        lines.append(f":maatlog-authors: {authors}")
    lines.extend(["", title, "=" * len(title), ""])
    if body:
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


REFERENCE_PROJECT: dict[str, str] = {
    "index.rst": """\
Root
====

Links:

* post: :maatlog:post:`Post Article <demo-post>`
* tag: :maatlog:tag:`Sphinx <sphinx>`
* category: :maatlog:category:`Engineering <engineering>`
* author: :maatlog:author:`Alice <alice>`
* month: :maatlog:month:`2026-07`

.. toctree::
   :hidden:

   post
   api
""",
    "post.rst": _rst_post(
        slug="demo-post",
        title="Demo Post",
        body="See API :py:func:`sample.hello`.",
    ),
    "api.rst": """\
API
===

.. py:function:: sample.hello

   Greet the reader.

See :maatlog:post:`demo-post`.
""",
}

REFERENCE_CONFIG = {
    "maatlog_timezone": "UTC",
    "maatlog_tags": {"sphinx": "Sphinx"},
    "maatlog_categories": {"engineering": "Engineering"},
    "maatlog_authors": {"alice": "Alice"},
    "maatlog_archive_docname": "blog",
}


def _href_for_text(html: str, link_text: str) -> str:
    """Find href of an anchor whose visible text matches *link_text* (ignoring nested tags)."""
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, flags=re.IGNORECASE | re.DOTALL):
        attrs, inner = match.group(1), match.group(2)
        visible = re.sub(r"<[^>]+>", "", inner)
        visible = re.sub(r"\s+", " ", visible).strip()
        if visible != link_text:
            continue
        href_match = re.search(r'\bhref="([^"]+)"', attrs)
        assert href_match is not None, f"anchor for {link_text!r} has no href:\n{match.group(0)}"
        return href_match.group(1)
    raise AssertionError(f"link with text {link_text!r} not found in HTML:\n{html}")


def _output_text(app: Sphinx, relative: str) -> str:
    return Path(app.outdir, relative).read_text(encoding="utf-8")


def test_archive_docname_matches_plan04_scheme() -> None:
    assert archive_docname("blog", None, None, 1) == "blog"
    assert archive_docname("blog", None, None, 2) == "blog/page/2"
    assert archive_docname("blog", TaxonomyAxis.TAG, "sphinx", 1) == "blog/tag/sphinx"
    assert archive_docname("blog", "tag", "sphinx", 2) == "blog/tag/sphinx/page/2"
    assert archive_docname("blog", TaxonomyAxis.MONTH, "2026-07", 1) == "blog/month/2026-07"


def test_post_and_taxonomy_roles_resolve(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=REFERENCE_PROJECT, config=REFERENCE_CONFIG, builder="html")
    app.build()

    html = _output_text(app, "index.html")
    assert _href_for_text(html, "Post Article").endswith("post.html")
    assert _href_for_text(html, "Sphinx").endswith("blog/tag/sphinx.html")
    assert _href_for_text(html, "Engineering").endswith("blog/category/engineering.html")
    assert _href_for_text(html, "Alice").endswith("blog/author/alice.html")
    assert _href_for_text(html, "2026-07").endswith("blog/month/2026-07.html")


def test_non_html_taxonomy_role_becomes_label(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=REFERENCE_PROJECT, config=REFERENCE_CONFIG, builder="text")
    app.build()

    text = _output_text(app, "index.txt")
    assert "Sphinx" in text
    assert "Engineering" in text
    assert "Alice" in text
    assert "2026-07" in text
    assert "Post Article" in text
    assert "blog/tag" not in text
    assert "blog/category" not in text
    assert "blog/author" not in text
    assert "blog/month" not in text

    # Text output can omit URIs even for reference nodes; assert node kinds in the
    # resolved doctree so taxonomy roles are proven to be inline labels, not links.
    # Do not key TextElement by astext: make_refnode yields reference > inline with
    # the same text, and the inner inline would mask a wrong reference parent.
    doctree = app.env.get_and_resolve_doctree("index", app.builder, tags=app.builder.tags)
    expected_labels = ("Sphinx", "Engineering", "Alice", "2026-07")
    for label in expected_labels:
        refs = [n for n in doctree.findall(nodes.reference) if n.astext() == label]
        assert not refs, f"{label!r} must not appear as nodes.reference"
        inlines = [
            n for n in doctree.findall(nodes.inline) if n.astext() == label and not isinstance(n, nodes.reference)
        ]
        assert inlines, f"{label!r} should resolve to nodes.inline"

    post_nodes = [node for node in doctree.findall(nodes.reference) if node.astext() == "Post Article"]
    assert post_nodes, "post role should remain a reference on non-HTML builders"


def test_unpublished_post_resolves_but_stays_out_of_inventory(
    make_sphinx: SphinxFactory,
) -> None:
    """Draft posts resolve via :maatlog:post: but are excluded from inventory.

    Taxonomy keys used only by drafts must neither resolve nor appear in
    ``get_objects()``.
    """
    files = {
        "index.rst": """\
Root
====

* live: :maatlog:post:`Live Post <live-post>`
* draft: :maatlog:post:`Draft Post <draft-post>`

.. toctree::
   :hidden:

   live
   draft
""",
        "live.rst": _rst_post(
            slug="live-post",
            title="Live Post",
            tags="sphinx",
            categories="",
            authors="",
        ),
        "draft.rst": _rst_post(
            slug="draft-post",
            title="Draft Post",
            published_at=None,
            tags="hidden-draft-tag",
            categories="",
            authors="",
        ),
    }
    config = {
        "maatlog_timezone": "UTC",
        "maatlog_tags": {"sphinx": "Sphinx", "hidden-draft-tag": "Hidden Draft Tag"},
        "maatlog_archive_docname": "blog",
    }
    app = make_sphinx(files=files, config=config, builder="html")
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)

    draft_ref = domain.lookup("post", "draft-post")
    assert draft_ref is not None
    assert draft_ref.docname == "draft"
    assert draft_ref.label == "Draft Post"

    live_ref = domain.lookup("post", "live-post")
    assert live_ref is not None
    assert live_ref.docname == "live"

    assert domain.lookup("tag", "hidden-draft-tag") is None
    assert domain.lookup("tag", "sphinx") is not None

    objects = list(domain.get_objects())
    post_slugs = {name for name, _disp, typ, *_rest in objects if typ == "post"}
    tag_keys = {name for name, _disp, typ, *_rest in objects if typ == "tag"}
    assert post_slugs == {"live-post"}
    assert "draft-post" not in post_slugs
    assert tag_keys == {"sphinx"}
    assert "hidden-draft-tag" not in tag_keys

    html = _output_text(app, "index.html")
    assert _href_for_text(html, "Draft Post").endswith("draft.html")
    assert _href_for_text(html, "Live Post").endswith("live.html")


def test_python_domain_interop(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=REFERENCE_PROJECT, config=REFERENCE_CONFIG, builder="html")
    app.build()

    api_html = _output_text(app, "api.html")
    post_html = _output_text(app, "post.html")
    assert _href_for_text(api_html, "demo-post").endswith("post.html")
    assert "sample.hello" in post_html
    assert 'href="#sample.hello"' in post_html or "sample.hello" in post_html


def test_get_objects_covers_five_types(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=REFERENCE_PROJECT, config=REFERENCE_CONFIG, builder="html")
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    objects = list(domain.get_objects())
    by_type: dict[str, list[tuple[str, str, str, str, str, int]]] = {}
    for item in objects:
        by_type.setdefault(item[2], []).append(item)

    assert set(by_type) == {"post", "tag", "category", "author", "month"}
    assert by_type["post"] == [("demo-post", "Demo Post", "post", "post", "", 1)]
    assert by_type["tag"] == [("sphinx", "Sphinx", "tag", "blog/tag/sphinx", "", 1)]
    assert by_type["category"] == [("engineering", "Engineering", "category", "blog/category/engineering", "", 1)]
    assert by_type["author"] == [("alice", "Alice", "author", "blog/author/alice", "", 1)]
    assert by_type["month"] == [("2026-07", "2026-07", "month", "blog/month/2026-07", "", 1)]


def test_missing_reference_returns_none(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "index.rst": "Root\n====\n\nNo dangling roles here.\n",
            "post.rst": _rst_post(slug="demo-post", title="Demo Post"),
        },
        config=REFERENCE_CONFIG,
        builder="html",
    )
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    assert domain.lookup("post", "missing-slug") is None
    assert domain.lookup("tag", "missing-tag") is None
    assert domain.lookup("month", "1999-01") is None

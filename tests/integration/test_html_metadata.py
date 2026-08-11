"""Integration tests for MaatLog HTML metadata: canonical, body, feed discovery."""

from __future__ import annotations

import pytest
from conftest import ProjectFactory, SphinxFactory

from maatlog.errors import MaatlogBuildError
from maatlog.html_metadata import (
    cleanup_body_fragment_store,
    prepare_body_fragment_store,
    read_body_fragment,
)

INTERNAL_POST = {
    "post.md": """---
maatlog-post: true
maatlog-slug: meta-internal
maatlog-published-at: 2026-08-01T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: A short summary.
---
# Internal Meta

Body visible on the MaatLog page.
""",
}

EXTERNAL_POST = {
    "post.md": """---
maatlog-post: true
maatlog-slug: meta-external
maatlog-published-at: 2026-08-01T09:00:00Z
maatlog-excerpt: Summary
maatlog-external-url: https://publisher.example/articles/42
---
# External Meta

Hidden local body
""",
}

CANONICAL_POST = {
    "post.md": """---
maatlog-post: true
maatlog-slug: meta-canonical
maatlog-published-at: 2026-08-01T09:00:00Z
maatlog-canonical-url: https://canonical.example/article
---
# Explicit Canonical

Body.
""",
}


def test_internal_post_head(make_project: ProjectFactory) -> None:
    result = make_project(
        files=INTERNAL_POST,
        config={"html_baseurl": "https://example.com/"},
    ).build()
    page = result.html("post.html")

    canonical = page.select_one('link[rel="canonical"]')
    assert canonical is not None
    assert canonical["href"] == "https://example.com/post.html"

    atom = page.select_one('link[type="application/atom+xml"]')
    assert atom is not None
    assert atom.get("rel") == "alternate"
    assert atom["href"] == "https://example.com/blog/atom.xml"
    assert "application/atom+xml" in page.text

    # Taxonomy feeds for the post's membership.
    assert "https://example.com/blog/tag/sphinx/atom.xml" in page.text
    assert "https://example.com/blog/category/engineering/atom.xml" in page.text
    assert "https://example.com/blog/author/alice/atom.xml" in page.text
    assert "https://example.com/blog/month/2026-08/atom.xml" in page.text

    # MaatLog does not emit OGP / Twitter Card meta tags.
    assert 'property="og:' not in page.text
    assert 'name="twitter:' not in page.text

    assert "Body visible on the MaatLog page." in page.text


def test_external_post_only_renders_summary(make_project: ProjectFactory) -> None:
    result = make_project(
        files=EXTERNAL_POST,
        config={"html_baseurl": "https://example.com/"},
    ).build()
    page = result.html("post.html")

    assert "Summary" in page.text
    assert "Hidden local body" not in page.text
    assert page.select_one(".maatlog-external-link") is not None
    assert "https://publisher.example/articles/42" in page.text


def test_explicit_canonical_url(make_project: ProjectFactory) -> None:
    result = make_project(
        files=CANONICAL_POST,
        config={"html_baseurl": "https://example.com/"},
    ).build()
    page = result.html("post.html")
    canonical = page.select_one('link[rel="canonical"]')
    assert canonical is not None
    assert canonical["href"] == "https://canonical.example/article"


def test_feeds_disabled_omits_atom_discovery(make_project: ProjectFactory) -> None:
    result = make_project(
        files=INTERNAL_POST,
        config={
            "html_baseurl": "https://example.com/",
            "maatlog_generate_feeds": False,
        },
    ).build()
    page = result.html("post.html")

    canonical = page.select_one('link[rel="canonical"]')
    assert canonical is not None
    assert canonical["href"] == "https://example.com/post.html"
    assert page.select_one('link[type="application/atom+xml"]') is None
    assert "atom.xml" not in page.text
    assert page.select_one(".maatlog-feed-links") is None


def test_missing_baseurl_fails_when_feeds_enabled(make_project: ProjectFactory) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.feed.baseurl-required"):
        make_project(
            files=INTERNAL_POST,
            config={"html_baseurl": ""},
        ).build()


def test_archive_head_includes_site_feed(make_project: ProjectFactory) -> None:
    result = make_project(
        files=INTERNAL_POST,
        config={"html_baseurl": "https://example.com/"},
    ).build()
    page = result.html("blog.html")
    atom = page.select_one('link[type="application/atom+xml"]')
    assert atom is not None
    assert atom["href"] == "https://example.com/blog/atom.xml"


TWO_INTERNAL_POSTS = {
    "alpha.md": """---
maatlog-post: true
maatlog-slug: alpha
maatlog-published-at: 2026-08-01T09:00:00Z
---
# Alpha

Alpha body fragment for feeds.
""",
    "beta.md": """---
maatlog-post: true
maatlog-slug: beta
maatlog-published-at: 2026-08-02T09:00:00Z
---
# Beta

Beta body fragment for feeds.
""",
}


def test_feed_bodies_are_complete_on_unchanged_incremental_rebuild(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        files=TWO_INTERNAL_POSTS,
        source_date_epoch="1788307200",
        config={"html_baseurl": "https://example.com/", "maatlog_generate_feeds": True},
    )
    project.build(reuse_environment=False)
    second = project.build(reuse_environment=True)
    atom = second.path("blog/atom.xml").read_text(encoding="utf-8")
    assert "Alpha body fragment for feeds." in atom
    assert "Beta body fragment for feeds." in atom


def test_missing_internal_body_record_is_fatal(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files=INTERNAL_POST,
        config={"html_baseurl": "https://example.com/"},
    )
    prepare_body_fragment_store(app, app.builder)
    try:
        with pytest.raises(MaatlogBuildError) as error:
            read_body_fragment(app, "post")
        assert error.value.diagnostics[0].code == "maatlog.feed.render-failed"
    finally:
        cleanup_body_fragment_store(app)

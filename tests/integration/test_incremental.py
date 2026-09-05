"""Incremental domain builds: add / change / delete match a clean rebuild."""

from __future__ import annotations

import re

from conftest import HtmlPage, ProjectFactory

from maatlog.model import PublicationStatus

_NAV_TAXONOMY_SECTIONS = re.compile(
    r'<section class="maatlog-taxonomy\b[^"]*">.*?</section>',
    re.DOTALL,
)


def _nav_taxonomy_html(page: HtmlPage) -> tuple[str, ...]:
    """Return ``.maatlog-nav .maatlog-taxonomy`` sections in document order."""
    marker = 'data-maatlog-component="nav"'
    start = page.text.find(marker)
    assert start != -1
    inner = page.text.find("<nav", start)
    end = page.text.find("</nav>", inner if inner != -1 else start)
    assert end != -1
    return tuple(_NAV_TAXONOMY_SECTIONS.findall(page.text[start:end]))


def _nav_taxonomy_hrefs(page: HtmlPage) -> list[str]:
    return [item.get("href", "") for item in page.select(".maatlog-nav .maatlog-taxonomy a")]


def _nav_toctree_hrefs(page: HtmlPage) -> list[str]:
    return [item.get("href", "") for item in page.select(".maatlog-nav-toctree a")]


def _nav_toctree_html(page: HtmlPage) -> str:
    """Return the inner HTML of ``.maatlog-nav-toctree``."""
    marker = 'class="maatlog-nav-toctree"'
    start = page.text.find(marker)
    assert start != -1
    open_end = page.text.find(">", start)
    close = page.text.find("</div>", open_end)
    assert open_end != -1 and close != -1
    return page.text[open_end + 1 : close]


def _rst_post(
    *,
    slug: str,
    published_at: str | None,
    tags: str = "",
    categories: str = "",
    authors: str = "",
    title: str | None = None,
) -> str:
    lines = [":maatlog-post: true", f":maatlog-slug: {slug}"]
    if published_at is not None:
        lines.append(f":maatlog-published-at: {published_at}")
    if tags:
        lines.append(f":maatlog-tags: {tags}")
    if categories:
        lines.append(f":maatlog-categories: {categories}")
    if authors:
        lines.append(f":maatlog-authors: {authors}")
    heading = title if title is not None else slug.replace("-", " ").title()
    lines.extend(["", heading, "=" * len(heading), "", f"Body for {slug}.", ""])
    return "\n".join(lines)


BASE_FILES = {
    "keep.rst": _rst_post(
        slug="keep",
        published_at="2026-07-01T00:00:00Z",
        tags="stable",
        categories="news",
        authors="alice",
    ),
    "removed-post.rst": _rst_post(
        slug="removed",
        published_at="2026-07-02T00:00:00Z",
        tags="gone",
        categories="news",
        authors="bob",
    ),
    "mutable.rst": _rst_post(
        slug="mutable",
        published_at="2026-07-03T00:00:00Z",
        tags="old-tag",
        categories="engineering",
        authors="alice",
    ),
    "draft.rst": _rst_post(slug="draft-only", published_at=None, tags="hidden"),
    "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
}

BASE_CONFIG = {"maatlog_timezone": "UTC"}


def test_incremental_delete_matches_clean_build(make_project: ProjectFactory) -> None:
    project = make_project(files=BASE_FILES, config=BASE_CONFIG)
    project.build(reuse_environment=False)

    project.remove("removed-post.rst")
    incremental = project.build(reuse_environment=True)
    clean = project.build(reuse_environment=False)

    assert incremental.domain_data("maatlog") == clean.domain_data("maatlog")
    snap = clean.domain_data("maatlog")
    assert "removed-post" not in snap.posts_by_docname
    assert "removed" not in snap.docname_by_slug
    assert set(snap.published_slugs) == {"mutable", "keep"}


def test_incremental_change_matches_clean_build(make_project: ProjectFactory) -> None:
    project = make_project(files=BASE_FILES, config=BASE_CONFIG)
    project.build(reuse_environment=False)

    project.write(
        "mutable.rst",
        _rst_post(
            slug="mutable",
            published_at="2026-07-20T00:00:00Z",
            tags="new-tag",
            categories="engineering",
            authors="carol",
            title="Mutable Updated",
        ),
    )
    incremental = project.build(reuse_environment=True)
    clean = project.build(reuse_environment=False)

    assert incremental.domain_data("maatlog") == clean.domain_data("maatlog")
    snap = clean.domain_data("maatlog")
    assert snap.posts_by_docname["mutable"].title == "Mutable Updated"
    assert snap.posts_by_docname["mutable"].tags == ("new-tag",)
    assert snap.posts_by_docname["mutable"].authors == ("carol",)
    assert snap.published_slugs[0] == "mutable"


def test_incremental_add_matches_clean_build(make_project: ProjectFactory) -> None:
    files = {k: v for k, v in BASE_FILES.items() if k != "removed-post.rst"}
    project = make_project(files=files, config=BASE_CONFIG)
    project.build(reuse_environment=False)

    project.write(
        "new-post.rst",
        _rst_post(
            slug="brand-new",
            published_at="2026-07-25T00:00:00Z",
            tags="fresh",
            categories="news",
            authors="dave",
        ),
    )
    incremental = project.build(reuse_environment=True)
    clean = project.build(reuse_environment=False)

    assert incremental.domain_data("maatlog") == clean.domain_data("maatlog")
    snap = clean.domain_data("maatlog")
    assert "new-post" in snap.posts_by_docname
    assert snap.posts_by_docname["new-post"].slug == "brand-new"
    assert "brand-new" in snap.published_slugs


def test_incremental_add_refreshes_plain_page_taxonomy_nav(make_project: ProjectFactory) -> None:
    """A new published tag must update left-nav taxonomies on untouched pages."""
    files = {
        "keep.rst": _rst_post(
            slug="keep",
            published_at="2026-07-01T00:00:00Z",
            tags="stable",
        ),
        "about.rst": "About\n=====\n\nA plain page that is not a post.\n",
    }
    project = make_project(files=files, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    first_hrefs = _nav_taxonomy_hrefs(first.html("about.html"))
    assert any(href.endswith("blog/tag/stable.html") for href in first_hrefs)
    assert not any(href.endswith("blog/tag/fresh.html") for href in first_hrefs)

    project.write(
        "new-post.rst",
        _rst_post(
            slug="brand-new",
            published_at="2026-07-25T00:00:00Z",
            tags="fresh",
        ),
    )
    incremental = project.build(reuse_environment=True)
    incremental_about = incremental.html("about.html")
    incremental_taxonomy = _nav_taxonomy_html(incremental_about)
    incremental_hrefs = _nav_taxonomy_hrefs(incremental_about)

    clean = project.build(reuse_environment=False)
    clean_about = clean.html("about.html")

    assert incremental_taxonomy == _nav_taxonomy_html(clean_about)
    assert any(href.endswith("blog/tag/fresh.html") for href in incremental_hrefs)


def test_incremental_title_change_refreshes_plain_page_toctree(make_project: ProjectFactory) -> None:
    files = {
        "post.rst": _rst_post(
            slug="post",
            published_at="2026-07-01T00:00:00Z",
            title="Old Post Title",
        ),
        "about.rst": "About\n=====\n\nPlain page.\n",
    }
    project = make_project(files=files, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    assert "Old Post Title" in first.html("about.html")

    project.write(
        "post.rst",
        _rst_post(
            slug="post",
            published_at="2026-07-01T00:00:00Z",
            title="New Post Title",
        ),
    )
    incremental = project.build(reuse_environment=True)

    assert "New Post Title" in incremental.html("about.html")
    assert "Old Post Title" not in incremental.html("about.html")


_TOCTREE_FILES = {
    "index.rst": "Root\n====\n\n.. toctree::\n\n   about\n   extra\n",
    "about.rst": "About\n=====\n\nPlain page.\n",
    "extra.rst": "Extra\n=====\n\nAnother plain page.\n",
}


def test_incremental_toctree_removal_refreshes_plain_page_nav(make_project: ProjectFactory) -> None:
    """Dropping a document from the master toctree must update untouched pages."""
    project = make_project(files=_TOCTREE_FILES, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    assert any(href.endswith("extra.html") for href in _nav_toctree_hrefs(first.html("about.html")))

    project.write("index.rst", "Root\n====\n\n.. toctree::\n\n   about\n")
    incremental = project.build(reuse_environment=True)
    incremental_hrefs = _nav_toctree_hrefs(incremental.html("about.html"))

    clean = project.build(reuse_environment=False)

    assert incremental_hrefs == _nav_toctree_hrefs(clean.html("about.html"))
    assert not any(href.endswith("extra.html") for href in incremental_hrefs)


def test_incremental_hidden_toctree_refreshes_plain_page_nav(make_project: ProjectFactory) -> None:
    """Moving a document into a ``:hidden:`` toctree must update untouched pages."""
    project = make_project(files=_TOCTREE_FILES, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    assert any(href.endswith("extra.html") for href in _nav_toctree_hrefs(first.html("about.html")))

    project.write(
        "index.rst",
        "Root\n====\n\n.. toctree::\n\n   about\n\n.. toctree::\n   :hidden:\n\n   extra\n",
    )
    incremental = project.build(reuse_environment=True)
    incremental_hrefs = _nav_toctree_hrefs(incremental.html("about.html"))

    clean = project.build(reuse_environment=False)

    assert incremental_hrefs == _nav_toctree_hrefs(clean.html("about.html"))
    assert not any(href.endswith("extra.html") for href in incremental_hrefs)


def test_incremental_explicit_toctree_title_refreshes_plain_page_nav(
    make_project: ProjectFactory,
) -> None:
    """Changing only an explicit toctree label must update untouched pages."""
    files = {
        "index.rst": """Root
====

.. toctree::

   About page <about>
   Extra page <extra>
""",
        "about.rst": "About\n=====\n\nPlain page.\n",
        "extra.rst": "Extra\n=====\n\nAnother plain page.\n",
    }
    project = make_project(files=files, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    first_nav = _nav_toctree_html(first.html("about.html"))
    assert "About page" in first_nav
    assert "Extra page" in first_nav

    project.write(
        "index.rst",
        """Root
====

.. toctree::

   Renamed about <about>
   Extra page <extra>
""",
    )
    incremental = project.build(reuse_environment=True)
    incremental_nav = _nav_toctree_html(incremental.html("about.html"))

    clean = project.build(reuse_environment=False)
    clean_nav = _nav_toctree_html(clean.html("about.html"))

    assert "Renamed about" in incremental_nav
    assert "About page" not in incremental_nav
    assert "Extra page" in incremental_nav
    assert incremental_nav == clean_nav


def test_incremental_includehidden_toctree_refreshes_plain_page_nav(
    make_project: ProjectFactory,
) -> None:
    """Adding ``:includehidden:`` to the master toctree must update untouched pages."""
    files = {
        "index.rst": """Root
====

.. toctree::

   about
   extra
""",
        "about.rst": "About\n=====\n\nPlain page.\n",
        "extra.rst": """Extra
=====

.. toctree::
   :hidden:

   secret
""",
        "secret.rst": "Secret\n======\n\nHidden child page.\n",
    }
    project = make_project(files=files, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    first_hrefs = _nav_toctree_hrefs(first.html("about.html"))
    assert any(href.endswith("extra.html") for href in first_hrefs)
    assert not any(href.endswith("secret.html") for href in first_hrefs)

    project.write(
        "index.rst",
        """Root
====

.. toctree::
   :includehidden:

   about
   extra
""",
    )
    incremental = project.build(reuse_environment=True)
    incremental_hrefs = _nav_toctree_hrefs(incremental.html("about.html"))

    clean = project.build(reuse_environment=False)

    assert any(href.endswith("secret.html") for href in incremental_hrefs)
    assert incremental_hrefs == _nav_toctree_hrefs(clean.html("about.html"))


def test_incremental_fingerprint_is_scoped_to_builder_and_outdir(make_project: ProjectFactory) -> None:
    files = {
        "keep.rst": _rst_post(
            slug="keep",
            published_at="2026-07-01T00:00:00Z",
            tags="stable",
        ),
        "about.rst": "About\n=====\n\nPlain page.\n",
    }
    project = make_project(files=files, config=BASE_CONFIG)
    project.builder = "html"
    project.outdir = project.root / "output-html"
    project.build(reuse_environment=False)
    project.builder = "dirhtml"
    project.outdir = project.root / "output-dirhtml"
    project.build(reuse_environment=True)

    project.write(
        "fresh.rst",
        _rst_post(
            slug="fresh",
            published_at="2026-07-02T00:00:00Z",
            tags="fresh",
        ),
    )
    project.builder = "html"
    project.outdir = project.root / "output-html"
    project.build(reuse_environment=True)
    project.builder = "dirhtml"
    project.outdir = project.root / "output-dirhtml"
    result = project.build(reuse_environment=True)

    hrefs = _nav_taxonomy_hrefs(result.html("about/index.html"))
    assert any(href.endswith("blog/tag/fresh/") for href in hrefs)


def test_publication_status_recomputed_at_finalize_without_source_change(
    make_project: ProjectFactory,
) -> None:
    """With feeds disabled, a later SOURCE_DATE_EPOCH publishes a scheduled post.

    Status refresh must happen in finalize/rebuild_index, not via feed-driven
    force-outdated re-reads of unchanged sources.
    """
    # 2026-07-01T00:00:00Z — before the scheduled publication.
    before_epoch = "1782864000"
    # 2026-08-15T00:00:00Z — after the scheduled publication.
    after_epoch = "1786752000"
    files = {
        "scheduled.md": """---
maatlog-post: true
maatlog-slug: future-post
maatlog-published-at: 2026-08-01T12:00:00Z
---
# Future Post

Scheduled body.
""",
    }
    project = make_project(
        files=files,
        source_date_epoch=before_epoch,
        config={"maatlog_generate_feeds": False, "maatlog_timezone": "UTC"},
    )
    first = project.build(reuse_environment=False)
    first_post = first.domain_data("maatlog").posts_by_docname["scheduled"]
    assert first_post.status is PublicationStatus.SCHEDULED
    assert "future-post" not in first.domain_data("maatlog").published_slugs
    first_blog = first.html("blog.html")
    # Archive cards exclude scheduled posts. Site toctree may still list the
    # unpublished title; that is accepted shell behavior.
    assert first_blog.select('.maatlog-post-card[data-slug="future-post"]') == []

    project.source_date_epoch = after_epoch
    second = project.build(reuse_environment=True)
    second_snap = second.domain_data("maatlog")
    assert second_snap.posts_by_docname["scheduled"].status is PublicationStatus.PUBLISHED
    assert "future-post" in second_snap.published_slugs
    second_blog = second.html("blog.html")
    assert second_blog.select_one('.maatlog-post-card[data-slug="future-post"]')


def test_post_list_docname_dropped_when_directive_removed(make_project: ProjectFactory) -> None:
    """Removing the directive from a source must drop the rewrite tracking."""
    files = {
        "listing.rst": "Listing\n=======\n\n.. maatlog:post-list::\n",
        "keep.rst": _rst_post(slug="keep", published_at="2026-07-01T00:00:00Z"),
    }
    project = make_project(files=files, config=BASE_CONFIG)
    first = project.build(reuse_environment=False)
    assert "listing" in first.domain_data("maatlog").post_list_docnames

    project.write("listing.rst", "Listing\n=======\n\nPlain page now.\n")
    second = project.build(reuse_environment=True)
    assert "listing" not in second.domain_data("maatlog").post_list_docnames


PROFILE_CONFIG = {
    "maatlog_authors": {"alice": "Alice Anderson"},
    "maatlog_author_profiles": {"alice": {"about_docname": "authors/alice"}},
}

PROFILE_INDEX = """Root
====

.. toctree::

   one
"""

PROFILE_POST = """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-authors: [alice]
---
# One

Body.
"""


def test_editing_only_the_about_document_refreshes_the_profile_page(make_project: ProjectFactory) -> None:
    site = make_project(
        files={
            "index.rst": PROFILE_INDEX,
            "one.md": PROFILE_POST,
            "authors/alice.md": "# About Alice\n\nFirst revision.\n",
        },
        config=PROFILE_CONFIG,
    )
    first = site.build()
    assert "First revision." in first.html("blog/author/alice.html")

    site.write("authors/alice.md", "# About Alice\n\nSecond revision.\n")
    second = site.build(reuse_environment=True)

    page = second.html("blog/author/alice.html")
    assert "Second revision." in page
    assert "First revision." not in page


def test_author_summary_survives_an_incremental_rebuild(make_project: ProjectFactory) -> None:
    site = make_project(
        files={"about.rst": "About\n=====\n\nBody.\n"},
        theme="maatlog-default",
        config={"maatlog_authors": {"alice": "Alice"}, "maatlog_default_author": "alice"},
    )
    site.build()
    result = site.build(reuse_environment=True)

    assert result.html("about.html").select_one(".maatlog-author-summary") is not None

"""Unit tests for archive projection, filtering, and pagination."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from maatlog.archives import (
    ArchiveKey,
    ArchivePage,
    PageSlice,
    PostFilter,
    check_generated_docnames,
    filter_posts,
    paginate,
    project_archives,
)
from maatlog.config import MaatlogConfig, TaxonomyAxis
from maatlog.errors import MaatlogBuildError
from maatlog.model import Post, PublicationStatus
from maatlog.references import archive_docname
from maatlog.taxonomy import build_domain_index


def test_archive_docnames() -> None:
    assert archive_docname("blog", None, None, 1) == "blog"
    assert archive_docname("blog", TaxonomyAxis.TAG, "sphinx", 2) == "blog/tag/sphinx/page/2"


def test_filters_or_within_axis_and_across_axes(filter_posts_input: Sequence[Post]) -> None:
    result = filter_posts(
        filter_posts_input,
        PostFilter(tags=("sphinx", "python"), authors=("alice",)),
        timezone=ZoneInfo("UTC"),
    )
    assert [post.slug for post in result] == ["both", "sphinx-only", "python-only"]


def test_filter_empty_means_no_constraint(filter_posts_input: Sequence[Post]) -> None:
    result = filter_posts(filter_posts_input, PostFilter(), timezone=ZoneInfo("UTC"))
    assert [post.slug for post in result] == [post.slug for post in filter_posts_input]


def test_filter_month_exact_uses_timezone() -> None:
    # 2026-07-31 16:00 UTC == 2026-08-01 01:00 Asia/Tokyo
    late = _post(
        docname="late",
        slug="late",
        published_at=datetime(2026, 7, 31, 16, 0, tzinfo=UTC),
        tags=("a",),
    )
    early = _post(
        docname="early",
        slug="early",
        published_at=datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
        tags=("a",),
    )
    posts = (late, early)
    tokyo = ZoneInfo("Asia/Tokyo")

    august = filter_posts(posts, PostFilter(month="2026-08"), timezone=tokyo)
    july = filter_posts(posts, PostFilter(month="2026-07"), timezone=tokyo)

    assert [post.slug for post in august] == ["late"]
    assert [post.slug for post in july] == ["early"]


def test_page_one_has_no_alias(paginated_posts: Sequence[Post]) -> None:
    pages = paginate(paginated_posts, page_size=2)
    assert [page.number for page in pages] == [1, 2, 3]
    assert pages[0].docname_suffix == ""
    assert pages[1].docname_suffix == "/page/2"
    assert pages[2].docname_suffix == "/page/3"
    assert pages[0].total_pages == 3
    assert [post.slug for post in pages[0].posts] == ["p1", "p2"]
    assert [post.slug for post in pages[2].posts] == ["p5"]


def test_paginate_empty_yields_single_empty_page() -> None:
    pages = paginate((), page_size=10)
    assert pages == (PageSlice(number=1, total_pages=1, posts=()),)
    assert pages[0].docname_suffix == ""


def test_project_archives_all_posts_even_when_empty() -> None:
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC"})
    index = build_domain_index({}, config)

    pages = project_archives(
        index,
        root="blog",
        page_size=10,
        timezone=config.timezone,
    )

    assert len(pages) == 1
    page = pages[0]
    assert page.docname == "blog"
    assert page.key == ArchiveKey(axis=None, value=None, label="Posts")
    assert page.number == 1
    assert page.total_pages == 1
    assert page.posts == ()
    assert page.total_posts == 0


def test_project_archives_skips_empty_taxonomy_and_paginates() -> None:
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC", "maatlog_page_size": 2})
    posts = {
        "a": _post(
            docname="a",
            slug="a",
            published_at=datetime(2026, 8, 3, tzinfo=UTC),
            tags=("sphinx", "python"),
            categories=("engineering",),
            authors=("alice",),
        ),
        "b": _post(
            docname="b",
            slug="b",
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
            tags=("sphinx",),
            categories=("engineering",),
            authors=("alice",),
        ),
        "c": _post(
            docname="c",
            slug="c",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            tags=("python",),
            authors=("bob",),
        ),
        "draft": _post(
            docname="draft",
            slug="draft",
            published_at=None,
            status=PublicationStatus.DRAFT,
            tags=("hidden",),
        ),
    }
    index = build_domain_index(posts, config)

    pages = project_archives(
        index,
        root="blog",
        page_size=2,
        timezone=config.timezone,
    )

    by_docname = {page.docname: page for page in pages}

    assert "blog" in by_docname
    assert by_docname["blog"].total_posts == 3
    assert by_docname["blog"].total_pages == 2
    assert [post.slug for post in by_docname["blog"].posts] == ["a", "b"]
    assert by_docname["blog/page/2"].number == 2
    assert [post.slug for post in by_docname["blog/page/2"].posts] == ["c"]

    assert "blog/tag/sphinx" in by_docname
    assert [post.slug for post in by_docname["blog/tag/sphinx"].posts] == ["a", "b"]
    assert "blog/tag/python" in by_docname
    assert [post.slug for post in by_docname["blog/tag/python"].posts] == ["a", "c"]
    assert "blog/tag/hidden" not in by_docname

    assert "blog/category/engineering" in by_docname
    assert "blog/author/alice" in by_docname
    assert by_docname["blog/author/alice"].total_posts == 2
    assert "blog/author/bob" in by_docname

    assert "blog/month/2026-08" in by_docname
    assert [post.slug for post in by_docname["blog/month/2026-08"].posts] == ["a", "b"]
    assert "blog/month/2026-07" in by_docname
    assert [post.slug for post in by_docname["blog/month/2026-07"].posts] == ["c"]

    assert isinstance(by_docname["blog"], ArchivePage)
    assert by_docname["blog/tag/sphinx"].key.axis is TaxonomyAxis.TAG
    assert by_docname["blog/tag/sphinx"].key.value == "sphinx"
    assert by_docname["blog/month/2026-08"].key.label == "2026-08"


def test_project_archives_uses_configured_labels() -> None:
    config = MaatlogConfig.from_values(
        {
            "maatlog_timezone": "UTC",
            "maatlog_tags": {"sphinx": "Sphinx"},
            "maatlog_authors": {"alice": "Alice"},
        }
    )
    posts = {
        "a": _post(
            docname="a",
            slug="a",
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            tags=("sphinx",),
            authors=("alice",),
        ),
    }
    index = build_domain_index(posts, config)
    pages = project_archives(index, root="notes", page_size=10, timezone=config.timezone)
    by_docname = {page.docname: page for page in pages}

    assert by_docname["notes/tag/sphinx"].key.label == "Sphinx"
    assert by_docname["notes/author/alice"].key.label == "Alice"
    assert by_docname["notes"].docname == "notes"


# --- fixtures / helpers -------------------------------------------------------


@pytest.fixture
def filter_posts_input() -> tuple[Post, ...]:
    return (
        _post(
            docname="both",
            slug="both",
            published_at=datetime(2026, 8, 5, tzinfo=UTC),
            tags=("sphinx", "python"),
            authors=("alice",),
        ),
        _post(
            docname="sphinx-only",
            slug="sphinx-only",
            published_at=datetime(2026, 8, 4, tzinfo=UTC),
            tags=("sphinx",),
            authors=("alice",),
        ),
        _post(
            docname="python-only",
            slug="python-only",
            published_at=datetime(2026, 8, 3, tzinfo=UTC),
            tags=("python",),
            authors=("alice",),
        ),
        _post(
            docname="bob-sphinx",
            slug="bob-sphinx",
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
            tags=("sphinx",),
            authors=("bob",),
        ),
        _post(
            docname="alice-other",
            slug="alice-other",
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            tags=("other",),
            authors=("alice",),
        ),
    )


@pytest.fixture
def paginated_posts() -> tuple[Post, ...]:
    return tuple(
        _post(
            docname=f"p{i}",
            slug=f"p{i}",
            published_at=datetime(2026, 8, 10 - i, tzinfo=UTC),
        )
        for i in range(1, 6)
    )


def test_check_generated_docnames_rejects_source_collision() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        check_generated_docnames(("blog", "blog/tag/x"), known_docnames={"blog", "index"})

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.generated-docname.conflict"
    assert diagnostic.field == "docname"
    assert diagnostic.value == "blog"
    assert diagnostic.expected == "unused relative docname"


def test_check_generated_docnames_rejects_internal_duplicates() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        check_generated_docnames(("blog", "blog/tag/x", "blog"), known_docnames=set())

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.generated-docname.conflict"
    assert diagnostic.value == "blog"


def test_check_generated_docnames_accepts_unused_names() -> None:
    check_generated_docnames(("blog", "blog/tag/x"), known_docnames={"index", "posts/hello"})


def _post(
    *,
    docname: str,
    slug: str,
    published_at: datetime | None,
    status: PublicationStatus | None = None,
    tags: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
    authors: tuple[str, ...] = (),
) -> Post:
    if status is None:
        status = PublicationStatus.PUBLISHED if published_at is not None else PublicationStatus.DRAFT
    return Post(
        docname=docname,
        source_path=f"{docname}.rst",
        title=slug,
        slug=slug,
        published_at=published_at,
        expires_at=None,
        tags=tags,
        categories=categories,
        authors=authors,
        excerpt=None,
        image_uri=None,
        canonical_url=None,
        external_url=None,
        status=status,
    )

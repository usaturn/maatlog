"""Unit tests for neighbors and taxonomy sidebar navigation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from maatlog.config import MaatlogConfig, TaxonomyAxis
from maatlog.model import Post, PublicationStatus
from maatlog.navigation import neighbors, taxonomy_navigation
from maatlog.taxonomy import build_domain_index

PostFactory = Callable[..., Post]


@pytest.fixture
def make_post() -> PostFactory:
    def factory(**overrides: Any) -> Post:
        values: dict[str, Any] = {
            "docname": "post",
            "source_path": "post.md",
            "title": "Title",
            "slug": "post",
            "published_at": datetime(2026, 7, 1, tzinfo=UTC),
            "expires_at": None,
            "tags": (),
            "categories": (),
            "authors": (),
            "excerpt": None,
            "image_uri": None,
            "canonical_url": None,
            "external_url": None,
            "status": PublicationStatus.PUBLISHED,
        }
        values.update(overrides)
        return Post(**values)

    return factory


def test_neighbors_skip_unpublished(make_post: PostFactory) -> None:
    # Published sequence only — drafts are already excluded by DomainIndex.
    published = (
        make_post(docname="new", slug="new", title="New", published_at=datetime(2026, 7, 3, tzinfo=UTC)),
        make_post(docname="middle", slug="middle", title="Middle", published_at=datetime(2026, 7, 2, tzinfo=UTC)),
        make_post(docname="old", slug="old", title="Old", published_at=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    newer, older = neighbors(published, "middle")
    assert newer is not None and newer.slug == "new"
    assert older is not None and older.slug == "old"


def test_neighbors_boundaries(make_post: PostFactory) -> None:
    published = (
        make_post(docname="new", slug="new", published_at=datetime(2026, 7, 2, tzinfo=UTC)),
        make_post(docname="old", slug="old", published_at=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    newer, older = neighbors(published, "new")
    assert newer is None
    assert older is not None and older.slug == "old"

    newer, older = neighbors(published, "old")
    assert newer is not None and newer.slug == "new"
    assert older is None


def test_neighbors_unknown_slug(make_post: PostFactory) -> None:
    published = (make_post(slug="only"),)
    assert neighbors(published, "missing") == (None, None)


def test_neighbors_stable_for_same_timestamp(make_post: PostFactory) -> None:
    # DomainIndex sorts by (-ts, slug, docname); unit test uses that order.
    same = datetime(2026, 7, 1, tzinfo=UTC)
    published = (
        make_post(docname="a-doc", slug="a", published_at=same),
        make_post(docname="b-doc", slug="b", published_at=same),
    )
    newer, older = neighbors(published, "a")
    assert newer is None
    assert older is not None and older.slug == "b"
    newer, older = neighbors(published, "b")
    assert newer is not None and newer.slug == "a"
    assert older is None


def test_taxonomy_navigation_sorts_labels_and_months_desc(make_post: PostFactory) -> None:
    config = MaatlogConfig.from_values(
        {
            "maatlog_timezone": "UTC",
            "maatlog_tags": {"zebra": "Zebra", "alpha": "Alpha"},
            "maatlog_categories": {"news": "News", "eng": "Engineering"},
            "maatlog_authors": {"bob": "Bob", "alice": "Alice"},
        }
    )
    posts = {
        "p1": make_post(
            docname="p1",
            slug="p1",
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
            tags=("zebra", "alpha"),
            categories=("news",),
            authors=("bob",),
        ),
        "p2": make_post(
            docname="p2",
            slug="p2",
            published_at=datetime(2026, 7, 15, tzinfo=UTC),
            tags=("alpha",),
            categories=("eng",),
            authors=("alice", "bob"),
        ),
        "draft": make_post(
            docname="draft",
            slug="draft",
            published_at=None,
            status=PublicationStatus.DRAFT,
            tags=("hidden",),
        ),
    }
    index = build_domain_index(posts, config)
    assert "hidden" not in index.members[TaxonomyAxis.TAG]

    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"uri:{to}"

    builder.get_relative_uri.side_effect = _relative_uri

    nav = taxonomy_navigation(index, builder=builder, from_docname="blog", root="blog")

    assert [item.id for item in nav.tags] == ["alpha", "zebra"]
    assert [item.label for item in nav.tags] == ["Alpha", "Zebra"]
    assert [item.count for item in nav.tags] == [2, 1]
    assert nav.tags[0].url == "uri:blog/tag/alpha"

    assert [item.label for item in nav.categories] == ["Engineering", "News"]
    assert [item.label for item in nav.authors] == ["Alice", "Bob"]
    assert nav.authors[1].count == 2  # bob on both posts

    assert [item.id for item in nav.months] == ["2026-08", "2026-07"]
    assert nav.months[0].count == 1
    assert nav.months[1].count == 1
    assert nav.months[0].url == "uri:blog/month/2026-08"

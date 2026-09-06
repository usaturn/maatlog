from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from maatlog.archives import ArchiveKey, ArchivePage
from maatlog.model import Post, PublicationStatus
from maatlog.views import (
    FEATURED_LIMIT,
    PostCardView,
    SiteView,
    archive_context,
    home_context,
    project_featured_latest,
)

PostFactory = Callable[..., Post]


@pytest.fixture
def post() -> PostFactory:
    def factory(**overrides: Any) -> Post:
        values: dict[str, Any] = {
            "docname": "blog/hello",
            "source_path": "blog/hello.md",
            "title": "Hello",
            "slug": "hello",
            "published_at": datetime(2026, 8, 1, tzinfo=UTC),
            "expires_at": None,
            "tags": ("release",),
            "categories": ("news",),
            "authors": ("maat",),
            "excerpt": None,
            "image_uri": None,
            "canonical_url": None,
            "external_url": None,
            "status": PublicationStatus.PUBLISHED,
        }
        values.update(overrides)
        return Post(**values)

    return factory


def _card(slug: str) -> PostCardView:
    return PostCardView(
        title=slug,
        page_url=f"{slug}.html",
        published_at=None,
        excerpt=None,
        image_url=None,
        tags=(),
        categories=(),
        authors=(),
        external_url=None,
        slug=slug,
    )


def _slugs(cards: Sequence[PostCardView]) -> tuple[str | None, ...]:
    return tuple(card.slug for card in cards)


def test_featured_limit_is_three() -> None:
    assert FEATURED_LIMIT == 3


def test_project_splits_default_featured_and_unlimited_latest() -> None:
    eligible = tuple(_card(f"p{i}") for i in range(5))
    featured, latest = project_featured_latest(eligible)
    assert _slugs(featured) == ("p0", "p1", "p2")
    assert _slugs(latest) == ("p3", "p4")


def test_project_truncates_latest_when_limit_is_set() -> None:
    eligible = tuple(_card(f"p{i}") for i in range(5))
    featured, latest = project_featured_latest(eligible, latest_limit=1)
    assert _slugs(featured) == ("p0", "p1", "p2")
    assert _slugs(latest) == ("p3",)


@pytest.mark.parametrize(
    ("count", "featured_slugs", "latest_slugs"),
    [
        (0, (), ()),
        (1, ("p0",), ()),
        (2, ("p0", "p1"), ()),
        (3, ("p0", "p1", "p2"), ()),
        (4, ("p0", "p1", "p2"), ("p3",)),
    ],
)
def test_project_uses_available_cards_below_the_featured_limit(
    count: int,
    featured_slugs: tuple[str, ...],
    latest_slugs: tuple[str, ...],
) -> None:
    eligible = tuple(_card(f"p{i}") for i in range(count))
    featured, latest = project_featured_latest(eligible, latest_limit=10)
    assert _slugs(featured) == featured_slugs
    assert _slugs(latest) == latest_slugs


def test_project_keeps_unselected_configured_cards_in_latest() -> None:
    eligible = tuple(_card(slug) for slug in ("lead", "a", "b", "kept", "tail"))
    featured, latest = project_featured_latest(
        eligible,
        featured=(_card("lead"), _card("a"), _card("b")),
        latest_limit=2,
    )
    assert _slugs(featured) == ("lead", "a", "b")
    assert _slugs(latest) == ("kept", "tail")


def test_project_does_not_drop_fourth_specified_from_latest() -> None:
    eligible = tuple(_card(slug) for slug in ("a", "b", "c", "d", "e"))
    specified = tuple(_card(slug) for slug in ("d", "a", "b", "c"))
    featured, latest = project_featured_latest(
        eligible,
        featured=specified[:FEATURED_LIMIT],
        latest_limit=10,
    )
    assert _slugs(featured) == ("d", "a", "b")
    assert "c" in _slugs(latest)


def _mock_builder() -> MagicMock:
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri
    builder.env = MagicMock()
    builder.env.images = {}
    builder.imagedir = "_images"
    return builder


def _newest_first(post: PostFactory, count: int) -> tuple[Post, ...]:
    items = tuple(
        post(
            docname=f"p{i}",
            slug=f"p{i}",
            title=f"P{i}",
            published_at=datetime(2026, 8, i + 1, tzinfo=UTC),
        )
        for i in range(count)
    )
    return tuple(reversed(items))


def test_home_context_uses_page_size_as_latest_cap(post: PostFactory) -> None:
    published = _newest_first(post, 5)
    context = home_context(
        published,
        _mock_builder(),
        docname="index",
        page_size=1,
        site=SiteView("Blog", None, "blog.html"),
    )
    assert _slugs(context.featured) == ("p4", "p3", "p2")
    assert _slugs(context.latest) == ("p1",)
    assert _slugs(context.posts) == ("p4", "p3", "p2", "p1")
    assert context.posts == context.featured + context.latest
    assert context.pagination is None


def test_home_context_excludes_the_home_document_from_both_columns(post: PostFactory) -> None:
    published = _newest_first(post, 3)
    context = home_context(
        published,
        _mock_builder(),
        docname="p2",
        page_size=10,
        site=SiteView("Blog", None, "blog.html"),
    )
    assert "p2" not in _slugs(context.featured)
    assert "p2" not in _slugs(context.latest)
    assert "p2" not in _slugs(context.posts)


def test_home_context_accepts_explicit_featured_posts(post: PostFactory) -> None:
    published = _newest_first(post, 5)
    pinned = next(item for item in published if item.slug == "p0")
    context = home_context(
        published,
        _mock_builder(),
        docname="index",
        page_size=2,
        site=SiteView("Blog", None, "blog.html"),
        featured_posts=(pinned,),
    )
    assert _slugs(context.featured) == ("p0",)
    assert _slugs(context.latest) == ("p4", "p3")
    assert "p0" not in _slugs(context.latest)


def test_home_context_converts_only_the_projection_window(post: PostFactory) -> None:
    # Card conversion is bounded by the projection window:
    # featured (max FEATURED_LIMIT) plus up to page_size latest cards.
    published = _newest_first(post, 20)
    builder = _mock_builder()
    page_size = 2
    context = home_context(
        published,
        builder,
        docname="index",
        page_size=page_size,
        site=SiteView("Blog", None, "blog.html"),
    )
    max_calls = FEATURED_LIMIT + page_size
    # Upper bound, not an exact count: one page-URL lookup per converted card.
    assert builder.get_relative_uri.call_count <= max_calls
    assert _slugs(context.featured) == ("p19", "p18", "p17")
    assert _slugs(context.latest) == ("p16", "p15")
    assert context.posts == context.featured + context.latest


def test_home_context_with_no_posts_has_empty_columns(post: PostFactory) -> None:
    context = home_context(
        (),
        _mock_builder(),
        docname="index",
        page_size=3,
        site=SiteView("Blog", None, "blog.html"),
    )
    assert context.featured == ()
    assert context.latest == ()
    assert context.posts == ()


def _archive_page(posts: tuple[Post, ...], *, number: int = 1) -> ArchivePage:
    return ArchivePage(
        key=ArchiveKey(axis=None, value=None, label="Posts"),
        docname="blog" if number == 1 else f"blog/page/{number}",
        number=number,
        total_pages=2,
        posts=posts,
        total_posts=4,
    )


def test_archive_home_splits_the_page_window(post: PostFactory) -> None:
    window = _newest_first(post, 4)[:2]  # p3, p2
    context = archive_context(_archive_page(window), _mock_builder(), is_home=True)
    assert _slugs(context.posts) == ("p3", "p2")
    assert _slugs(context.featured) == ("p3", "p2")
    assert context.latest == ()


def test_archive_home_keeps_window_posts_when_featured_is_pinned_outside(
    post: PostFactory,
) -> None:
    published = _newest_first(post, 4)
    window = published[:2]  # p3, p2
    pinned = next(item for item in published if item.slug == "p0")
    context = archive_context(
        _archive_page(window),
        _mock_builder(),
        is_home=True,
        featured_posts=(pinned,),
    )
    assert _slugs(context.featured) == ("p0",)
    assert _slugs(context.latest) == ("p3", "p2")
    assert _slugs(context.posts) == ("p3", "p2")


def test_non_home_archive_ignores_featured_posts(post: PostFactory) -> None:
    window = _newest_first(post, 2)
    context = archive_context(
        _archive_page(window, number=2),
        _mock_builder(),
        is_home=False,
        featured_posts=window,
    )
    assert context.featured == ()
    assert context.latest == ()
    assert _slugs(context.posts) == tuple(item.slug for item in window)

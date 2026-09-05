"""Unit tests for neighbors and taxonomy sidebar navigation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from maatlog import navigation as navigation_module
from maatlog.config import MaatlogConfig, TaxonomyAxis
from maatlog.model import Post, PublicationStatus
from maatlog.navigation import (
    PostTaxonomyLinker,
    _axis_rows,  # pyright: ignore[reportPrivateUsage]
    _cached_axis_rows,  # pyright: ignore[reportPrivateUsage]
    neighbors,
    post_taxonomy_linker,
    taxonomy_navigation,
)
from maatlog.taxonomy import DomainIndex, build_domain_index
from maatlog.views import TaxonomyLinkView

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


def test_post_taxonomy_linker_builds_links_for_each_axis(make_post: PostFactory) -> None:
    posts = {
        "post": make_post(
            docname="post",
            slug="post",
            tags=("sphinx",),
            categories=("engineering",),
            authors=("alice",),
        )
    }
    config = MaatlogConfig.from_values(
        {
            "maatlog_tags": {"sphinx": "Sphinx"},
            "maatlog_categories": {"engineering": "Engineering"},
            "maatlog_authors": {"alice": "Alice"},
        }
    )
    index = build_domain_index(posts, config)
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri

    linker = post_taxonomy_linker(index, builder=builder, from_docname="post", root="blog")
    taxonomies = linker.for_post(posts["post"])

    assert taxonomies.tags == (TaxonomyLinkView(id="sphinx", label="Sphinx", url="blog/tag/sphinx.html"),)
    assert taxonomies.categories == (
        TaxonomyLinkView(id="engineering", label="Engineering", url="blog/category/engineering.html"),
    )
    assert taxonomies.authors == (TaxonomyLinkView(id="alice", label="Alice", url="blog/author/alice.html"),)


def test_post_taxonomy_linker_falls_back_to_id_when_label_missing(make_post: PostFactory) -> None:
    post = make_post(tags=("unknown",))
    builder = MagicMock()

    linker = post_taxonomy_linker(None, builder=builder, from_docname="post", root="blog")
    taxonomies = linker.for_post(post)

    assert taxonomies.tags == (TaxonomyLinkView(id="unknown", label="unknown", url=""),)
    builder.get_relative_uri.assert_not_called()


def test_post_taxonomy_linker_uses_empty_url_when_uri_fails(make_post: PostFactory) -> None:
    post = make_post(docname="post", slug="post", tags=("sphinx",))
    index = build_domain_index(
        {"post": post},
        MaatlogConfig.from_values({}),
    )
    builder = MagicMock()
    builder.get_relative_uri.side_effect = RuntimeError("no uri")

    linker = post_taxonomy_linker(index, builder=builder, from_docname="post", root="blog")
    taxonomies = linker.for_post(post)

    assert taxonomies.tags == (TaxonomyLinkView(id="sphinx", label="sphinx", url=""),)


def test_post_taxonomy_linker_memoizes_resolved_urls(make_post: PostFactory) -> None:
    first = make_post(docname="a", slug="a", tags=("sphinx",))
    second = make_post(docname="b", slug="b", tags=("sphinx",))
    index = build_domain_index(
        {"a": first, "b": second},
        MaatlogConfig.from_values({}),
    )
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri

    linker = post_taxonomy_linker(index, builder=builder, from_docname="post", root="blog")
    linker.for_post(first)
    linker.for_post(second)

    assert builder.get_relative_uri.call_count == 1


def test_post_taxonomy_linker_links_only_published_membership(make_post: PostFactory) -> None:
    published = make_post(docname="published", slug="published", tags=("shared",))
    scheduled = make_post(
        docname="scheduled",
        slug="scheduled",
        tags=("shared", "secret"),
        status=PublicationStatus.SCHEDULED,
    )
    index = build_domain_index(
        {"published": published, "scheduled": scheduled},
        MaatlogConfig.from_values({}),
    )
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri

    taxonomies = post_taxonomy_linker(
        index,
        builder=builder,
        from_docname="scheduled",
        root="blog",
    ).for_post(scheduled)

    assert taxonomies.tags == (
        TaxonomyLinkView(id="shared", label="shared", url="blog/tag/shared.html"),
        TaxonomyLinkView(id="secret", label="secret", url=""),
    )
    assert builder.get_relative_uri.call_count == 1


def _source_to_target(source: str, target: str) -> str:
    return f"{source}->{target}"


def _index_with_two_tags(make_post: PostFactory) -> DomainIndex:
    config = MaatlogConfig.from_values(
        {
            "maatlog_timezone": "UTC",
            "maatlog_tags": {"zebra": "Zebra", "alpha": "Alpha"},
        }
    )
    posts = {
        "p1": make_post(
            docname="p1", slug="p1", published_at=datetime(2026, 8, 2, tzinfo=UTC), tags=("zebra", "alpha")
        ),
        "p2": make_post(docname="p2", slug="p2", published_at=datetime(2026, 7, 15, tzinfo=UTC), tags=("alpha",)),
    }
    return build_domain_index(posts, config)


def test_axis_rows_are_page_independent(make_post: PostFactory) -> None:
    index = _index_with_two_tags(make_post)

    rows = _axis_rows(index, axis=TaxonomyAxis.TAG, root="blog", reverse=False, sort_by_label=True)

    assert [row.id for row in rows] == ["alpha", "zebra"]
    assert [row.label for row in rows] == ["Alpha", "Zebra"]
    assert [row.count for row in rows] == [2, 1]
    assert [row.target_docname for row in rows] == ["blog/tag/alpha", "blog/tag/zebra"]


def test_taxonomy_navigation_produces_same_links_from_two_pages(make_post: PostFactory) -> None:
    index = _index_with_two_tags(make_post)
    builder = MagicMock()
    builder.get_relative_uri.side_effect = _source_to_target

    from_root = taxonomy_navigation(index, builder=builder, from_docname="index", root="blog")
    from_deep = taxonomy_navigation(index, builder=builder, from_docname="contents/post", root="blog")

    assert [item.id for item in from_root.tags] == [item.id for item in from_deep.tags]
    assert from_root.tags[0].url == "index->blog/tag/alpha"
    assert from_deep.tags[0].url == "contents/post->blog/tag/alpha"


def test_cached_axis_rows_key_covers_the_ordering_parameters(make_post: PostFactory) -> None:
    """Memoisation must not latch the ordering of whichever call came first."""
    index = _index_with_two_tags(make_post)
    builder = MagicMock()

    ascending = _cached_axis_rows(
        index, builder=builder, axis=TaxonomyAxis.TAG, root="blog", reverse=False, sort_by_label=True
    )
    descending = _cached_axis_rows(
        index, builder=builder, axis=TaxonomyAxis.TAG, root="blog", reverse=True, sort_by_label=True
    )

    assert [row.id for row in ascending] == ["alpha", "zebra"]
    assert [row.id for row in descending] == ["zebra", "alpha"]


def test_taxonomy_navigation_computes_rows_once_per_builder(
    make_post: PostFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _index_with_two_tags(make_post)
    builder = MagicMock()
    builder.get_relative_uri.side_effect = _source_to_target

    calls: list[TaxonomyAxis] = []
    original = navigation_module._axis_rows  # pyright: ignore[reportPrivateUsage]

    def counting(index_arg: DomainIndex, **kwargs: Any) -> tuple[Any, ...]:
        calls.append(kwargs["axis"])
        return original(index_arg, **kwargs)

    monkeypatch.setattr(navigation_module, "_axis_rows", counting)

    first = taxonomy_navigation(index, builder=builder, from_docname="index", root="blog")
    computed_after_first = len(calls)
    second = taxonomy_navigation(index, builder=builder, from_docname="about", root="blog")

    # 4 軸 (tag / category / author / month) を 1 度だけ集計し、2 度目はキャッシュを使う。
    assert computed_after_first == 4
    assert len(calls) == 4
    assert [item.id for item in first.tags] == [item.id for item in second.tags]


def test_taxonomy_navigation_recomputes_when_index_changes(make_post: PostFactory) -> None:
    builder = MagicMock()
    builder.get_relative_uri.side_effect = _source_to_target

    first_index = _index_with_two_tags(make_post)
    first = taxonomy_navigation(first_index, builder=builder, from_docname="index", root="blog")
    assert [item.id for item in first.tags] == ["alpha", "zebra"]

    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC", "maatlog_tags": {"gamma": "Gamma"}})
    second_index = build_domain_index(
        {"p3": make_post(docname="p3", slug="p3", published_at=datetime(2026, 9, 1, tzinfo=UTC), tags=("gamma",))},
        config,
    )
    second = taxonomy_navigation(second_index, builder=builder, from_docname="index", root="blog")

    assert [item.id for item in second.tags] == ["gamma"]


def _labelled_index(make_post: PostFactory) -> DomainIndex:
    """タグ 2 つ・記事 2 本の最小インデックス。"""
    config = MaatlogConfig.from_values(
        {
            "maatlog_timezone": "UTC",
            "maatlog_tags": {"alpha": "Alpha", "zebra": "Zebra"},
        }
    )
    posts = {
        "p1": make_post(
            docname="p1",
            slug="p1",
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
            tags=("alpha", "zebra"),
        ),
        "p2": make_post(
            docname="p2",
            slug="p2",
            published_at=datetime(2026, 7, 15, tzinfo=UTC),
            tags=("alpha",),
        ),
    }
    return build_domain_index(posts, config)


def _uri_builder() -> MagicMock:
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"uri:{to}"

    builder.get_relative_uri.side_effect = _relative_uri
    return builder


def test_taxonomy_item_is_current_on_its_own_archive(make_post: PostFactory) -> None:
    index = _labelled_index(make_post)

    nav = taxonomy_navigation(index, builder=_uri_builder(), from_docname="blog/tag/alpha", root="blog")

    current = {item.id: item.is_current for item in nav.tags}
    assert current == {"alpha": True, "zebra": False}


def test_taxonomy_item_is_current_on_a_paginated_archive(make_post: PostFactory) -> None:
    # ページ送りされた 2 ページ目でも現在地として点灯する。
    index = _labelled_index(make_post)

    nav = taxonomy_navigation(index, builder=_uri_builder(), from_docname="blog/tag/alpha/page/2", root="blog")

    assert [item.is_current for item in nav.tags if item.id == "alpha"] == [True]


def test_taxonomy_item_is_not_current_elsewhere(make_post: PostFactory) -> None:
    index = _labelled_index(make_post)

    nav = taxonomy_navigation(index, builder=_uri_builder(), from_docname="about", root="blog")

    assert not any(item.is_current for item in nav.tags)


def test_taxonomy_item_is_not_current_for_a_prefix_lookalike(make_post: PostFactory) -> None:
    # "blog/tag/alpha" は "blog/tag/alphabet" の接頭辞。素朴な startswith では誤判定する。
    index = _labelled_index(make_post)

    nav = taxonomy_navigation(index, builder=_uri_builder(), from_docname="blog/tag/alphabet", root="blog")

    assert not any(item.is_current for item in nav.tags)


def test_for_authors_keeps_the_given_order_and_resolves_labels() -> None:
    linker = PostTaxonomyLinker(
        builder=_uri_builder(),
        from_docname="about",
        root="blog",
        labels={TaxonomyAxis.AUTHOR: {"bob": "Bob", "alice": "Alice"}},
        members={TaxonomyAxis.AUTHOR: {"alice": ("one",), "bob": ("two",)}},
    )

    links = linker.for_authors(("bob", "alice"))

    assert [link.id for link in links] == ["bob", "alice"]
    assert [link.label for link in links] == ["Bob", "Alice"]


def test_for_authors_leaves_the_url_empty_for_an_author_without_posts() -> None:
    linker = PostTaxonomyLinker(
        builder=_uri_builder(),
        from_docname="about",
        root="blog",
        labels={TaxonomyAxis.AUTHOR: {"carol": "Carol"}},
        members={TaxonomyAxis.AUTHOR: {}},
    )

    (link,) = linker.for_authors(("carol",))

    assert link.url == ""
    assert link.label == "Carol"

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from maatlog.archives import ArchiveKey, ArchivePage
from maatlog.model import Post, PublicationStatus
from maatlog.views import (
    FeedLinkView,
    MaatlogTemplateContext,
    PostTaxonomiesView,
    SiteView,
    TaxonomyItemView,
    TaxonomyLinkView,
    TaxonomyNavigationView,
    archive_view,
    as_template_mapping,
    build_post_context,
    empty_context,
    home_context,
    normal_page_context,
    post_card_view,
    post_view,
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


def test_empty_context_has_all_public_keys() -> None:
    context = empty_context()
    assert tuple(asdict(context)) == (
        "api_version",
        "version",
        "page_kind",
        "post",
        "posts",
        "archive",
        "pagination",
        "navigation",
        "feeds",
        "taxonomies",
        "site",
    )
    assert context.api_version == "1.5"
    assert context.site == SiteView(title="", tagline=None, archive_url="")


def test_context_exposes_the_maatlog_distribution_version() -> None:
    from maatlog.version import PACKAGE_VERSION

    context = empty_context()

    assert context.version == PACKAGE_VERSION
    assert context.version != context.api_version


def test_empty_context_defaults() -> None:
    context = empty_context()
    assert context.api_version == "1.5"
    assert context.page_kind == "normal"
    assert context.post is None
    assert context.posts == ()
    assert context.archive is None
    assert context.pagination is None
    assert context.navigation.newer_post is None
    assert context.navigation.older_post is None
    assert context.feeds == ()
    assert context.taxonomies.tags == ()
    assert context.taxonomies.categories == ()
    assert context.taxonomies.authors == ()
    assert context.taxonomies.months == ()
    assert context.site == SiteView(title="", tagline=None, archive_url="")


def test_external_post_does_not_expose_body_html(post: PostFactory) -> None:
    view = post_view(
        post(external_url="https://outside.example/x", excerpt="Summary"),
        body_html="secret",
    )
    assert view.body_html is None
    assert view.excerpt == "Summary"
    assert view.external_url == "https://outside.example/x"


def test_internal_post_keeps_body_html(post: PostFactory) -> None:
    view = post_view(post(), body_html="<p>Body</p>")
    assert view.body_html == "<p>Body</p>"


def test_build_post_context_sets_page_kind(post: PostFactory) -> None:
    context = build_post_context(post(), body_html="<p>x</p>", page_url="hello.html")
    assert context.page_kind == "post"
    assert context.post is not None
    assert context.post.page_url == "hello.html"
    assert context.post.body_html == "<p>x</p>"
    mapping = as_template_mapping(context)
    assert mapping["api_version"] == "1.5"
    assert mapping["page_kind"] == "post"
    assert mapping["post"]["body_html"] == "<p>x</p>"


def test_as_template_mapping_preserves_public_key_order() -> None:
    mapping = as_template_mapping(MaatlogTemplateContext())
    assert tuple(mapping) == (
        "api_version",
        "version",
        "page_kind",
        "post",
        "posts",
        "archive",
        "pagination",
        "navigation",
        "feeds",
        "taxonomies",
        "site",
    )


def test_post_taxonomies_view_empty_has_all_axes() -> None:
    empty = PostTaxonomiesView.empty()
    assert empty.tags == ()
    assert empty.categories == ()
    assert empty.authors == ()


def test_post_card_view_defaults_to_empty_taxonomies(post: PostFactory) -> None:
    card = post_card_view(post())
    assert card.taxonomies == PostTaxonomiesView.empty()
    # 1.0 の文字列タプルはそのまま残る。
    assert card.tags == ("release",)


def test_archive_view_is_home_defaults_to_false() -> None:
    page = ArchivePage(
        key=ArchiveKey(axis=None, value=None, label="Posts"),
        docname="blog",
        number=1,
        total_pages=1,
        posts=(),
        total_posts=0,
    )
    assert archive_view(page).is_home is False


def test_post_card_view_uses_supplied_taxonomies(post: PostFactory) -> None:
    links = PostTaxonomiesView(
        tags=(TaxonomyLinkView(id="release", label="Release", url="blog/tag/release.html"),),
        categories=(),
        authors=(),
    )
    card = post_card_view(post(), taxonomies=links)
    assert card.taxonomies == links


def test_home_context_shape(post: PostFactory) -> None:
    published = tuple(
        post(docname=f"p{n}", slug=f"p{n}", title=f"P{n}", published_at=datetime(2026, 8, n + 1, tzinfo=UTC))
        for n in range(5)
    )
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri
    site = SiteView(title="Blog", tagline="Notes", archive_url="blog.html")

    context = home_context(published, builder, docname="index", page_size=3, site=site)

    assert context.page_kind == "home"
    assert context.pagination is None
    assert context.site == site
    assert len(context.posts) == 3
    assert context.posts[0].page_url == "p0.html"
    assert context.archive is not None
    assert context.archive.is_home is True
    assert context.archive.kind == "all"
    assert context.archive.id is None
    assert context.archive.label == "Posts"
    assert context.archive.docname == "index"
    assert context.archive.page_number == 1
    assert context.archive.total_posts == 5


def test_home_context_with_no_posts(post: PostFactory) -> None:
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri
    context = home_context((), builder, docname="index", page_size=3, site=SiteView("Blog", None, "blog.html"))
    assert context.posts == ()
    assert context.archive is not None
    assert context.archive.total_posts == 0
    assert context.archive.is_home is True


def test_home_context_applies_linker(post: PostFactory) -> None:
    links = PostTaxonomiesView(
        tags=(TaxonomyLinkView(id="release", label="Release", url="blog/tag/release.html"),),
        categories=(),
        authors=(),
    )
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri
    context = home_context(
        (post(),),
        builder,
        docname="index",
        page_size=3,
        site=SiteView("Blog", None, "blog.html"),
        linker=lambda _post: links,
    )
    assert context.posts[0].taxonomies == links


def test_archive_view_is_home_can_be_set() -> None:
    page = ArchivePage(
        key=ArchiveKey(axis=None, value=None, label="Posts"),
        docname="blog",
        number=1,
        total_pages=1,
        posts=(),
        total_posts=0,
    )
    assert archive_view(page, is_home=True).is_home is True


def test_normal_page_context_keeps_page_kind_normal() -> None:
    site = SiteView(title="Blog", tagline="Notes", archive_url="blog.html")
    taxonomies = TaxonomyNavigationView(
        tags=(TaxonomyItemView(id="sphinx", label="Sphinx", count=2, url="blog/tag/sphinx.html"),),
        categories=(),
        authors=(),
        months=(),
    )
    feeds = (FeedLinkView(title="Posts", url="https://example.test/atom.xml"),)

    context = normal_page_context(site=site, taxonomies=taxonomies, feeds=feeds)

    assert context.page_kind == "normal"
    assert context.api_version == "1.5"
    assert context.post is None
    assert context.posts == ()
    assert context.archive is None
    assert context.pagination is None
    assert context.site == site
    assert context.taxonomies.tags[0].label == "Sphinx"
    assert context.feeds == feeds


def test_normal_page_context_defaults_to_empty_navigation() -> None:
    site = SiteView(title="Blog", tagline=None, archive_url="blog.html")

    context = normal_page_context(site=site)

    assert context.taxonomies == TaxonomyNavigationView.empty()
    assert context.feeds == ()


def test_empty_context_stays_empty() -> None:
    # 非 HTML ビルダー向けの経路は据え置き。
    context = empty_context(site=SiteView(title="Blog", tagline=None, archive_url="blog.html"))

    assert context.taxonomies == TaxonomyNavigationView.empty()
    assert context.feeds == ()

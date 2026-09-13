from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from maatlog.archives import ArchiveKey, ArchivePage
from maatlog.authors import AuthorLink, AuthorProfile
from maatlog.model import Post, PublicationStatus
from maatlog.views import (
    AuthorLinkView,
    AuthorProfileView,
    AuthorStatsView,
    AuthorSummaryView,
    FeedLinkView,
    MaatlogTemplateContext,
    PostTaxonomiesView,
    SiteView,
    TaxonomyItemView,
    TaxonomyLinkView,
    TaxonomyNavigationView,
    archive_context,
    archive_view,
    as_template_mapping,
    author_link_views,
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
        "metadata",
        "post",
        "posts",
        "featured",
        "latest",
        "archive",
        "pagination",
        "navigation",
        "feeds",
        "taxonomies",
        "site",
        "profile",
        "author_summaries",
    )
    assert context.api_version == "1.22"
    assert context.site == SiteView(title="", tagline=None, archive_url="")


def test_context_exposes_the_maatlog_distribution_version() -> None:
    from maatlog.version import PACKAGE_VERSION

    context = empty_context()

    assert context.version == PACKAGE_VERSION
    assert context.version != context.api_version


def test_empty_context_defaults() -> None:
    context = empty_context()
    assert context.api_version == "1.22"
    assert context.page_kind == "normal"
    assert context.post is None
    assert context.posts == ()
    assert context.featured == ()
    assert context.latest == ()
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


def test_canonical_url_is_dropped_when_it_is_not_absolute(post: PostFactory) -> None:
    """相対 canonical は不正。ブラウザは文書からの相対として解決するため URL がずれる。

    ``html_baseurl`` が無いと ``absolute_doc_url()`` は builder の target URI をそのまま
    返すので、この保護が無いと記事ページが到達不能な canonical を出す。
    """
    view = post_view(post(), page_url="posts/deep.html")

    assert view.page_url == "posts/deep.html"
    assert view.canonical_url is None


def test_canonical_url_is_kept_when_absolute(post: PostFactory) -> None:
    view = post_view(post(), page_url="https://example.test/posts/deep.html")

    assert view.canonical_url == "https://example.test/posts/deep.html"


def test_explicit_canonical_metadata_survives_a_relative_page_url(post: PostFactory) -> None:
    view = post_view(post(canonical_url="https://example.test/elsewhere.html"), page_url="posts/deep.html")

    assert view.canonical_url == "https://example.test/elsewhere.html"


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
    assert mapping["api_version"] == "1.22"
    assert mapping["page_kind"] == "post"
    assert mapping["post"]["body_html"] == "<p>x</p>"


def test_as_template_mapping_preserves_public_key_order() -> None:
    mapping = as_template_mapping(MaatlogTemplateContext())
    assert tuple(mapping) == (
        "api_version",
        "version",
        "page_kind",
        "metadata",
        "post",
        "posts",
        "featured",
        "latest",
        "archive",
        "pagination",
        "navigation",
        "feeds",
        "taxonomies",
        "site",
        "profile",
        "author_summaries",
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
        post(
            docname=f"p{n}",
            slug=f"p{n}",
            title=f"P{n}",
            published_at=datetime(2026, 8, 5 - n, tzinfo=UTC),
        )
        for n in range(5)
    )
    # p0 が 8/5 で最新 → 列は p0, p1, p2, p3, p4
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri
    site = SiteView(title="Blog", tagline="Notes", archive_url="blog.html")

    context = home_context(published, builder, docname="index", page_size=3, site=site)

    assert context.page_kind == "home"
    assert context.pagination is None
    assert context.site == site
    assert [card.slug for card in context.featured] == ["p0", "p1", "p2"]
    assert [card.slug for card in context.latest] == ["p3", "p4"]
    assert [card.slug for card in context.posts] == ["p0", "p1", "p2", "p3", "p4"]
    assert context.posts[0].page_url == "p0.html"
    assert len(context.posts) == 5
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
    assert context.api_version == "1.22"
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


def test_author_link_views_maps_profile_links() -> None:
    profile = AuthorProfile(
        links=(
            AuthorLink(type="github", url="https://github.com/alice", label="GitHub", icon="github"),
            AuthorLink(type="mastodon", url="https://example.social/@alice", label="mastodon", icon="link"),
        )
    )

    assert author_link_views(profile) == (
        AuthorLinkView(type="github", url="https://github.com/alice", label="GitHub", icon="github"),
        AuthorLinkView(type="mastodon", url="https://example.social/@alice", label="mastodon", icon="link"),
    )


def test_author_link_views_returns_empty_without_a_profile() -> None:
    assert author_link_views(None) == ()
    assert author_link_views(AuthorProfile(links=())) == ()


def test_post_view_has_top_image_fields(post: PostFactory) -> None:
    """PostView must carry top_image_url and top_image_alt."""
    view = post_view(
        post(),
        top_image_url="/_images/hero.png",
        top_image_alt="Hero",
    )
    assert view.top_image_url == "/_images/hero.png"
    assert view.top_image_alt == "Hero"


def test_post_view_top_image_defaults(post: PostFactory) -> None:
    view = post_view(post())
    assert view.top_image_url is None
    assert view.top_image_alt == ""


def test_site_view_top_image_title_font_default() -> None:
    site = SiteView(title="Blog", tagline=None, archive_url="/blog/")
    assert site.top_image_title_font is None


def test_site_view_content_width_default() -> None:
    site = SiteView(title="Blog", tagline=None, archive_url="/blog/")
    assert site.content_width is None


def test_site_view_content_width_is_carried_verbatim() -> None:
    site = SiteView(title="Blog", tagline=None, archive_url="/blog/", content_width="100%")
    assert site.content_width == "100%"


EMPTY_STATS = AuthorStatsView(post_count=0, writing_since=None, latest_post=None)


def test_empty_context_exposes_a_profile_key() -> None:
    mapping = as_template_mapping(empty_context())

    assert mapping["profile"] is None
    assert mapping["page_kind"] == "normal"


def test_profile_view_survives_the_template_mapping() -> None:
    profile = AuthorProfileView(
        slug="alice",
        display_name="Alice Anderson",
        role="Editor",
        avatar_url="_images/alice.png",
        initials="AA",
        bio_short="Hello.",
        interests=("Python",),
        links=(),
        about_html="<p>About</p>",
        featured=(),
        stats=EMPTY_STATS,
    )

    mapping = as_template_mapping(MaatlogTemplateContext(page_kind="profile", profile=profile))

    assert mapping["page_kind"] == "profile"
    assert mapping["profile"]["display_name"] == "Alice Anderson"
    assert mapping["profile"]["stats"]["post_count"] == 0


def test_author_summary_view_exposes_its_public_fields() -> None:
    from maatlog.views import AuthorSummaryView

    view = AuthorSummaryView(
        slug="alice",
        display_name="Alice Anderson",
        avatar_url=None,
        initials="AA",
        bio_short="Python developer.",
        links=(),
        profile_url="blog/author/alice.html",
    )

    assert tuple(asdict(view)) == (
        "slug",
        "display_name",
        "avatar_url",
        "initials",
        "bio_short",
        "links",
        "profile_url",
    )


def test_empty_context_has_no_author_summaries() -> None:
    assert empty_context().author_summaries == ()


def _summary(slug: str) -> AuthorSummaryView:
    return AuthorSummaryView(
        slug=slug,
        display_name=slug.title(),
        avatar_url=None,
        initials=slug[0].upper(),
        bio_short=None,
        links=(),
        profile_url=f"blog/author/{slug}.html",
    )


def _mock_builder() -> MagicMock:
    builder = MagicMock()

    def _relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    builder.get_relative_uri.side_effect = _relative_uri
    return builder


def test_normal_page_context_carries_author_summaries() -> None:
    context = normal_page_context(author_summaries=(_summary("alice"),))

    assert [item.slug for item in context.author_summaries] == ["alice"]


def test_build_post_context_carries_author_summaries(post: PostFactory) -> None:
    context = build_post_context(post(), author_summaries=(_summary("bob"), _summary("alice")))

    assert [item.slug for item in context.author_summaries] == ["bob", "alice"]


def test_archive_context_carries_author_summaries() -> None:
    page = ArchivePage(
        key=ArchiveKey(axis=None, value=None, label="Posts"),
        docname="blog",
        number=1,
        total_pages=1,
        posts=(),
        total_posts=0,
    )

    context = archive_context(page, _mock_builder(), author_summaries=(_summary("alice"),))

    assert [item.slug for item in context.author_summaries] == ["alice"]


def test_home_context_carries_author_summaries(post: PostFactory) -> None:
    context = home_context(
        (),
        _mock_builder(),
        docname="index",
        page_size=10,
        site=SiteView("Site", None, "blog.html"),
        author_summaries=(_summary("alice"),),
    )

    assert [item.slug for item in context.author_summaries] == ["alice"]

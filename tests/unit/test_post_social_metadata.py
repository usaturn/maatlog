from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

from maatlog.social_metadata import SocialMetadataView, project_social_metadata
from maatlog.social_metadata.post import project_post_metadata
from maatlog.views import (
    AuthorSummaryView,
    MaatlogTemplateContext,
    PostTaxonomiesView,
    PostView,
    SiteView,
    TaxonomyLinkView,
)

PAGE_URL = "https://example.test/docs/posts/hello.html"

HOSTILE = "Quote \" apostrophe ' backslash \\ <b> & </script> 日本語   \nnewline"


def make_post(**overrides: Any) -> PostView:
    """A minimal internal post; every field a test cares about is overridable."""
    fields: dict[str, Any] = {
        "title": "Hello World",
        "slug": "hello",
        "docname": "posts/hello",
        "page_url": PAGE_URL,
        "canonical_url": PAGE_URL,
        "external_url": None,
        "published_at": datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        "expires_at": None,
        "excerpt": "An excerpt.",
        "image_url": None,
        "tags": (),
        "categories": (),
        "authors": (),
        "body_html": "<p>Body</p>",
        "top_image_url": None,
        "top_image_alt": "",
        "taxonomies": PostTaxonomiesView.empty(),
    }
    fields.update(overrides)
    return PostView(**fields)


def make_context(post: PostView, **overrides: Any) -> MaatlogTemplateContext:
    fields: dict[str, Any] = {
        "page_kind": "post",
        "post": post,
        "site": SiteView(title="Example Blog", tagline="Tagline", archive_url="blog.html"),
    }
    fields.update(overrides)
    return MaatlogTemplateContext(**fields)


def open_graph(view: SocialMetadataView) -> list[tuple[str, str]]:
    return [(item.property, item.content) for item in view.open_graph]


def test_internal_post_emits_basic_open_graph() -> None:
    view = project_post_metadata(make_context(make_post(published_at=None)), page_url=PAGE_URL)

    assert open_graph(view) == [
        ("og:type", "article"),
        ("og:title", "Hello World"),
        ("og:site_name", "Example Blog"),
        ("og:url", PAGE_URL),
        ("og:description", "An excerpt."),
    ]


def test_explicit_canonical_wins_over_page_url() -> None:
    # A fragment-bearing canonical is preserved byte-for-byte by the real metadata input.
    post = make_post(canonical_url="https://example.test/elsewhere.html?utm=1#top")
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert ("og:url", "https://example.test/elsewhere.html?utm=1#top") in open_graph(view)


def test_missing_values_are_omitted_not_emptied() -> None:
    post = make_post(canonical_url=None, excerpt="   ", published_at=None)
    context = make_context(post, site=SiteView(title="", tagline=None, archive_url="blog.html"))
    view = project_post_metadata(context, page_url=None)

    assert open_graph(view) == [("og:type", "article"), ("og:title", "Hello World")]


def test_post_page_without_post_view_is_empty() -> None:
    view = project_post_metadata(MaatlogTemplateContext(page_kind="post"), page_url=PAGE_URL)

    assert view.open_graph == ()
    assert view.twitter == ()
    assert view.json_ld is None


def test_dispatcher_reaches_the_post_projector() -> None:
    view = project_social_metadata(make_context(make_post()), page_url=PAGE_URL)

    assert ("og:type", "article") in open_graph(view)


def twitter(view: SocialMetadataView) -> list[tuple[str, str]]:
    return [(item.name, item.content) for item in view.twitter]


def test_representative_image_wins_over_maattop_and_carries_no_alt() -> None:
    post = make_post(image_url="../_images/hero.png", top_image_url="../_images/top.png", top_image_alt="Top")
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert ("og:image", "https://example.test/docs/_images/hero.png") in open_graph(view)
    assert [name for name, _ in open_graph(view) if name == "og:image:alt"] == []
    assert ("twitter:card", "summary_large_image") in twitter(view)
    assert ("twitter:image", "https://example.test/docs/_images/hero.png") in twitter(view)


def test_maattop_is_the_second_candidate_and_carries_its_alt() -> None:
    post = make_post(top_image_url="../_images/top.png", top_image_alt="  A hero  ")
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert ("og:image", "https://example.test/docs/_images/top.png") in open_graph(view)
    assert ("og:image:alt", "A hero") in open_graph(view)
    assert ("twitter:image:alt", "A hero") in twitter(view)


def test_blank_maattop_alt_is_omitted() -> None:
    post = make_post(top_image_url="../_images/top.png", top_image_alt="   ")
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert [name for name, _ in open_graph(view) if name.endswith(":alt")] == []


def test_image_that_cannot_be_absolutized_drops_every_image_property() -> None:
    post = make_post(image_url="../_images/hero.png")
    view = project_post_metadata(make_context(post), page_url=None)

    assert [name for name, _ in open_graph(view) if name.startswith("og:image")] == []
    assert ("twitter:card", "summary") in twitter(view)
    assert [name for name, _ in twitter(view) if name.startswith("twitter:image")] == []


def test_no_fallthrough_to_maattop_when_the_representative_image_fails() -> None:
    # The representative image has no page URL to absolutize against, yet the ``maattop``
    # is an absolute URL that *could* be resolved. §5.2 forbids falling through to it: the
    # chosen candidate is not swapped just because it failed (both candidates resolve
    # against the same page URL), so every image property is dropped even though a
    # candidate was resolvable. A fallthrough implementation would emit the hero here.
    post = make_post(image_url="../_images/hero.png", top_image_url="https://cdn.example.test/hero.png")
    view = project_post_metadata(make_context(post), page_url=None)

    assert [name for name, _ in open_graph(view) if name.startswith("og:image")] == []
    assert [name for name, _ in twitter(view) if name.startswith("twitter:image")] == []
    assert ("twitter:card", "summary") in twitter(view)


def test_twitter_card_mirrors_the_open_graph_text() -> None:
    view = project_post_metadata(make_context(make_post()), page_url=PAGE_URL)

    assert twitter(view) == [
        ("twitter:card", "summary"),
        ("twitter:title", "Hello World"),
        ("twitter:description", "An excerpt."),
    ]


def test_open_graph_image_properties_follow_the_description() -> None:
    post = make_post(top_image_url="../_images/top.png", top_image_alt="A hero", published_at=None)
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert [name for name, _ in open_graph(view)] == [
        "og:type",
        "og:title",
        "og:site_name",
        "og:url",
        "og:description",
        "og:image",
        "og:image:alt",
    ]


def test_published_time_and_taxonomies_keep_source_order() -> None:
    post = make_post(
        tags=("sphinx", "python"),
        categories=("engineering",),
        taxonomies=PostTaxonomiesView(
            tags=(
                TaxonomyLinkView(id="sphinx", label="Sphinx", url="blog/tag/sphinx.html"),
                TaxonomyLinkView(id="python", label="Python", url="blog/tag/python.html"),
            ),
            categories=(TaxonomyLinkView(id="engineering", label="Engineering", url="blog/category/eng.html"),),
            authors=(),
        ),
    )
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert [(name, content) for name, content in open_graph(view) if name.startswith("article:")] == [
        ("article:published_time", "2026-09-01T12:00:00+00:00"),
        ("article:tag", "Sphinx"),
        ("article:tag", "Python"),
        ("article:section", "Engineering"),
    ]


def test_taxonomy_ids_are_used_when_labels_are_unresolved() -> None:
    post = make_post(tags=("sphinx", "python"), taxonomies=PostTaxonomiesView.empty())
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert [content for name, content in open_graph(view) if name == "article:tag"] == ["sphinx", "python"]


def test_draft_post_omits_published_time() -> None:
    view = project_post_metadata(make_context(make_post(published_at=None)), page_url=PAGE_URL)

    assert [name for name, _ in open_graph(view) if name == "article:published_time"] == []


def json_ld(view: SocialMetadataView) -> dict[str, Any]:
    assert view.json_ld is not None
    document = json.loads(view.json_ld)
    assert isinstance(document, dict)
    return cast("dict[str, Any]", document)


def test_blog_posting_projects_every_available_value() -> None:
    post = make_post(
        top_image_url="../_images/top.png",
        top_image_alt="A hero",
        tags=("sphinx",),
        categories=("engineering",),
        taxonomies=PostTaxonomiesView(
            tags=(TaxonomyLinkView(id="sphinx", label="Sphinx", url="blog/tag/sphinx.html"),),
            categories=(TaxonomyLinkView(id="engineering", label="Engineering", url="blog/category/eng.html"),),
            authors=(),
        ),
    )
    document = json_ld(project_post_metadata(make_context(post), page_url=PAGE_URL))

    assert list(document) == [
        "@context",
        "@type",
        "headline",
        "description",
        "datePublished",
        "url",
        "image",
        "keywords",
        "articleSection",
    ]
    assert document["@context"] == "https://schema.org"
    assert document["@type"] == "BlogPosting"
    assert document["headline"] == "Hello World"
    assert document["description"] == "An excerpt."
    assert document["datePublished"] == "2026-09-01T12:00:00+00:00"
    assert document["url"] == PAGE_URL
    assert document["image"] == ["https://example.test/docs/_images/top.png"]
    assert document["keywords"] == ["Sphinx"]
    assert document["articleSection"] == ["Engineering"]


def test_blog_posting_keeps_only_the_values_that_exist() -> None:
    post = make_post(canonical_url=None, excerpt=None, published_at=None)
    document = json_ld(project_post_metadata(make_context(post), page_url=None))

    assert document == {"@context": "https://schema.org", "@type": "BlogPosting", "headline": "Hello World"}


def test_titleless_post_emits_no_json_ld() -> None:
    view = project_post_metadata(make_context(make_post(title="   ")), page_url=PAGE_URL)

    assert view.json_ld is None


def summary(slug: str, name: str, profile_url: str) -> AuthorSummaryView:
    return AuthorSummaryView(
        slug=slug,
        display_name=name,
        avatar_url=None,
        initials=name[:1],
        bio_short=None,
        links=(),
        profile_url=profile_url,
    )


def test_hostile_text_survives_json_ld_round_trip() -> None:
    post = make_post(title=HOSTILE, excerpt=HOSTILE, authors=("alice",))
    context = make_context(post, author_summaries=(summary("alice", HOSTILE, ""),))
    view = project_post_metadata(context, page_url=PAGE_URL)

    assert view.json_ld is not None
    for unsafe in ("<", ">", "&", "\u2028", "\u2029"):
        assert unsafe not in view.json_ld
    assert "</script>" not in view.json_ld
    document = json_ld(view)
    assert document["headline"] == HOSTILE
    assert document["description"] == HOSTILE
    assert document["author"] == [{"@type": "Person", "name": HOSTILE}]
    assert ("og:title", HOSTILE) in open_graph(view)


def test_non_http_urls_never_reach_the_output() -> None:
    post = make_post(
        canonical_url="javascript:alert(1)",
        image_url="data:image/png;base64,AAAA",
        authors=("alice",),
    )
    context = make_context(post, author_summaries=(summary("alice", "Alice", "mailto:alice@example.test"),))
    view = project_post_metadata(context, page_url=None)

    assert [name for name, _ in open_graph(view) if name in {"og:url", "og:image"}] == []
    assert json_ld(view).get("author") == [{"@type": "Person", "name": "Alice"}]


def test_every_author_becomes_its_own_person_in_source_order() -> None:
    post = make_post(authors=("alice", "bob"))
    context = make_context(
        post,
        author_summaries=(
            summary("alice", "Alice Anderson", "../blog/author/alice.html"),
            summary("bob", "Bob Brown", ""),
        ),
    )
    document = json_ld(project_post_metadata(context, page_url=PAGE_URL))

    assert document["author"] == [
        {
            "@type": "Person",
            "name": "Alice Anderson",
            "url": "https://example.test/docs/blog/author/alice.html",
        },
        {"@type": "Person", "name": "Bob Brown"},
    ]


def test_author_without_a_summary_falls_back_to_the_resolved_id() -> None:
    context = make_context(make_post(authors=("carol",)), author_summaries=())
    document = json_ld(project_post_metadata(context, page_url=PAGE_URL))

    assert document["author"] == [{"@type": "Person", "name": "carol"}]


def test_post_without_authors_has_no_author_key() -> None:
    context = make_context(make_post(), author_summaries=(summary("dave", "Dave", "../blog/author/dave.html"),))
    document = json_ld(project_post_metadata(context, page_url=PAGE_URL))

    assert "author" not in document


def test_author_keys_sit_after_image_and_before_keywords() -> None:
    post = make_post(authors=("alice",), tags=("sphinx",))
    context = make_context(post, author_summaries=(summary("alice", "Alice", "../blog/author/alice.html"),))
    document = json_ld(project_post_metadata(context, page_url=PAGE_URL))

    assert list(document) == [
        "@context",
        "@type",
        "headline",
        "description",
        "datePublished",
        "url",
        "author",
        "keywords",
    ]


EXTERNAL_URL = "https://elsewhere.test/articles/hello"


def make_external_post(**overrides: Any) -> PostView:
    fields: dict[str, Any] = {"external_url": EXTERNAL_URL, "body_html": None}
    fields.update(overrides)
    return make_post(**fields)


def test_external_post_is_a_website_summary_of_the_external_url() -> None:
    post = make_external_post(tags=("sphinx",), categories=("engineering",))
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert open_graph(view) == [
        ("og:type", "website"),
        ("og:title", "Hello World"),
        ("og:site_name", "Example Blog"),
        ("og:url", EXTERNAL_URL),
        ("og:description", "An excerpt."),
    ]
    assert view.json_ld is None


def test_external_post_keeps_the_same_card_and_image_rules() -> None:
    post = make_external_post(top_image_url="../_images/top.png", top_image_alt="A hero")
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert ("og:image", "https://example.test/docs/_images/top.png") in open_graph(view)
    assert ("og:image:alt", "A hero") in open_graph(view)
    assert twitter(view) == [
        ("twitter:card", "summary_large_image"),
        ("twitter:title", "Hello World"),
        ("twitter:description", "An excerpt."),
        ("twitter:image", "https://example.test/docs/_images/top.png"),
        ("twitter:image:alt", "A hero"),
    ]


def test_external_post_never_falls_back_to_the_local_page_url() -> None:
    post = make_external_post(external_url="not-a-url")
    view = project_post_metadata(make_context(post), page_url=PAGE_URL)

    assert [name for name, _ in open_graph(view) if name == "og:url"] == []

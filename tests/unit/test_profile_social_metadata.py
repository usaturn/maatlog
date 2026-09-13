"""Unit coverage for the author profile social metadata projector (issue #210)."""

from __future__ import annotations

import json
from typing import cast

import pytest

from maatlog.social_metadata import SocialMetadataView
from maatlog.social_metadata.profile import project_profile_metadata
from maatlog.views import (
    AuthorLinkView,
    AuthorProfileView,
    AuthorStatsView,
    MaatlogTemplateContext,
    SiteView,
)

PAGE_URL = "https://example.test/docs/blog/author/alice.html"
AVATAR_URL = "https://example.test/docs/_images/alice.png"

STATS = AuthorStatsView(post_count=2, writing_since=2026, latest_post=None)

DEFAULT_LINKS = (
    AuthorLinkView(type="github", url="https://github.com/alice", label="GitHub", icon="github"),
    AuthorLinkView(type="mastodon", url="https://social.example/@alice", label="Mastodon", icon="link"),
)


def profile_view(
    *,
    display_name: str = "Alice Anderson",
    avatar_url: str | None = "../../_images/alice.png",
    bio_short: str | None = "Python developer.",
    links: tuple[AuthorLinkView, ...] = DEFAULT_LINKS,
) -> AuthorProfileView:
    return AuthorProfileView(
        slug="alice",
        display_name=display_name,
        role="Editor",
        avatar_url=avatar_url,
        initials="AA",
        bio_short=bio_short,
        interests=("Python",),
        links=links,
        about_html="<p>About body.</p>",
        featured=(),
        stats=STATS,
    )


def context_for(profile: AuthorProfileView | None, *, site_title: str = "Example Blog") -> MaatlogTemplateContext:
    return MaatlogTemplateContext(
        page_kind="profile",
        profile=profile,
        site=SiteView(title=site_title, tagline=None, archive_url="../../"),
    )


def og_pairs(view: SocialMetadataView) -> list[tuple[str, str]]:
    return [(item.property, item.content) for item in view.open_graph]


def twitter_pairs(view: SocialMetadataView) -> list[tuple[str, str]]:
    return [(item.name, item.content) for item in view.twitter]


def test_full_profile_projects_open_graph_in_a_fixed_order() -> None:
    view = project_profile_metadata(context_for(profile_view()), page_url=PAGE_URL)

    assert og_pairs(view) == [
        ("og:type", "profile"),
        ("og:title", "Alice Anderson"),
        ("og:site_name", "Example Blog"),
        ("og:url", PAGE_URL),
        ("og:description", "Python developer."),
        ("og:image", AVATAR_URL),
    ]


def test_full_profile_projects_a_summary_card() -> None:
    view = project_profile_metadata(context_for(profile_view()), page_url=PAGE_URL)

    assert twitter_pairs(view) == [
        ("twitter:card", "summary"),
        ("twitter:title", "Alice Anderson"),
        ("twitter:description", "Python developer."),
        ("twitter:image", AVATAR_URL),
    ]


def test_card_stays_summary_without_an_avatar() -> None:
    # An avatar is a square portrait, so the card never upgrades to summary_large_image.
    view = project_profile_metadata(context_for(profile_view(avatar_url=None)), page_url=PAGE_URL)

    assert twitter_pairs(view) == [
        ("twitter:card", "summary"),
        ("twitter:title", "Alice Anderson"),
        ("twitter:description", "Python developer."),
    ]
    assert "og:image" not in [name for name, _ in og_pairs(view)]


def test_image_descriptions_and_name_parts_are_never_invented() -> None:
    # No avatar description is configurable, and splitting a display name or exposing
    # the author id as profile:username would publish data MaatLog does not have.
    view = project_profile_metadata(context_for(profile_view()), page_url=PAGE_URL)

    names = [name for name, _ in og_pairs(view)] + [name for name, _ in twitter_pairs(view)]
    assert "og:image:alt" not in names
    assert "twitter:image:alt" not in names
    assert not any(name.startswith("profile:") for name in names)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_bio_omits_every_description(blank: str) -> None:
    view = project_profile_metadata(context_for(profile_view(bio_short=blank)), page_url=PAGE_URL)

    assert "og:description" not in [name for name, _ in og_pairs(view)]
    assert "twitter:description" not in [name for name, _ in twitter_pairs(view)]


def test_blank_site_title_omits_site_name() -> None:
    view = project_profile_metadata(context_for(profile_view(), site_title="  "), page_url=PAGE_URL)

    assert "og:site_name" not in [name for name, _ in og_pairs(view)]


def test_without_a_page_url_only_url_free_properties_remain() -> None:
    view = project_profile_metadata(context_for(profile_view()), page_url=None)

    assert og_pairs(view) == [
        ("og:type", "profile"),
        ("og:title", "Alice Anderson"),
        ("og:site_name", "Example Blog"),
        ("og:description", "Python developer."),
    ]
    assert twitter_pairs(view) == [
        ("twitter:card", "summary"),
        ("twitter:title", "Alice Anderson"),
        ("twitter:description", "Python developer."),
    ]


def test_absolute_avatar_survives_without_a_page_url() -> None:
    view = project_profile_metadata(
        context_for(profile_view(avatar_url="https://cdn.example/alice.png")), page_url=None
    )

    assert ("og:image", "https://cdn.example/alice.png") in og_pairs(view)


@pytest.mark.parametrize("avatar", ["data:image/png;base64,AAAA", "ftp://example.test/a.png", "   "])
def test_non_http_avatar_is_dropped(avatar: str) -> None:
    view = project_profile_metadata(context_for(profile_view(avatar_url=avatar)), page_url=PAGE_URL)

    assert "og:image" not in [name for name, _ in og_pairs(view)]
    assert "twitter:image" not in [name for name, _ in twitter_pairs(view)]


def test_blank_display_name_drops_the_title_but_keeps_the_type() -> None:
    view = project_profile_metadata(context_for(profile_view(display_name="   ")), page_url=PAGE_URL)

    assert "og:title" not in [name for name, _ in og_pairs(view)]
    assert "twitter:title" not in [name for name, _ in twitter_pairs(view)]
    assert ("og:type", "profile") in og_pairs(view)


def test_missing_profile_projects_nothing() -> None:
    # The dispatcher only routes page 1 of a configured author here, but the projector
    # stays total so a future caller cannot crash the build.
    assert project_profile_metadata(context_for(None), page_url=PAGE_URL) == SocialMetadataView()


#: Every character that could end the <script> element or start an entity, plus the raw
#: JavaScript line terminators. Kept away from both ends so ``str.strip()`` cannot quietly
#: remove the interesting part: U+2028 and U+2029 are whitespace to Python.
HOSTILE_TEXT = "Alice</script><b>&\"'\\ \u2028 \u2029 日本語\n end"


def json_ld_of(view: SocialMetadataView) -> dict[str, object]:
    assert view.json_ld is not None
    document = json.loads(view.json_ld)
    assert isinstance(document, dict)
    return cast("dict[str, object]", document)


def main_entity_of(view: SocialMetadataView) -> dict[str, object]:
    entity = json_ld_of(view)["mainEntity"]
    assert isinstance(entity, dict)
    return cast("dict[str, object]", entity)


def test_full_profile_projects_profile_page_json_ld() -> None:
    view = project_profile_metadata(context_for(profile_view()), page_url=PAGE_URL)

    assert json_ld_of(view) == {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": "Alice Anderson",
            "description": "Python developer.",
            "image": AVATAR_URL,
            "url": PAGE_URL,
            "sameAs": ["https://github.com/alice", "https://social.example/@alice"],
        },
    }


def test_json_ld_keeps_only_the_name_when_nothing_else_is_known() -> None:
    view = project_profile_metadata(
        context_for(profile_view(avatar_url=None, bio_short=None, links=()), site_title=""),
        page_url=None,
    )

    assert json_ld_of(view) == {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {"@type": "Person", "name": "Alice Anderson"},
    }


def test_json_ld_never_carries_guessed_dates_or_unmapped_profile_fields() -> None:
    # role and interests are free text; dateCreated / dateModified have no source at all.
    view = project_profile_metadata(context_for(profile_view()), page_url=PAGE_URL)

    assert set(json_ld_of(view)) == {"@context", "@type", "mainEntity"}
    assert set(main_entity_of(view)) == {"@type", "name", "description", "image", "url", "sameAs"}


def test_same_as_keeps_configuration_order_including_duplicates() -> None:
    links = (
        AuthorLinkView(type="site", url="https://example.test/alice", label="Site", icon="link"),
        AuthorLinkView(type="github", url="https://github.com/alice", label="GitHub", icon="github"),
        AuthorLinkView(type="mirror", url="https://example.test/alice", label="Mirror", icon="link"),
    )

    view = project_profile_metadata(context_for(profile_view(links=links)), page_url=PAGE_URL)

    assert main_entity_of(view)["sameAs"] == [
        "https://example.test/alice",
        "https://github.com/alice",
        "https://example.test/alice",
    ]


def test_same_as_is_absent_rather_than_empty() -> None:
    view = project_profile_metadata(context_for(profile_view(links=())), page_url=PAGE_URL)

    assert "sameAs" not in main_entity_of(view)


def test_same_as_survives_without_a_page_url() -> None:
    # Configured links are already absolute, so losing html_baseurl must not drop them.
    view = project_profile_metadata(context_for(profile_view()), page_url=None)

    assert main_entity_of(view)["sameAs"] == ["https://github.com/alice", "https://social.example/@alice"]
    assert "url" not in main_entity_of(view)


def test_blank_display_name_drops_the_json_ld() -> None:
    # Person.name is required, so an unnamed person gets no document at all.
    view = project_profile_metadata(context_for(profile_view(display_name=" ")), page_url=PAGE_URL)

    assert view.json_ld is None


def test_display_name_equal_to_slug_is_still_the_public_name() -> None:
    # maatlog_authors=None uses the taxonomy id as the page heading; metadata follows.
    view = project_profile_metadata(context_for(profile_view(display_name="alice")), page_url=PAGE_URL)

    assert main_entity_of(view)["name"] == "alice"
    assert ("og:title", "alice") in og_pairs(view)
    assert ("twitter:title", "alice") in twitter_pairs(view)
    names = [name for name, _ in og_pairs(view)] + [name for name, _ in twitter_pairs(view)]
    assert not any(name.startswith("profile:") for name in names)


def test_hostile_text_cannot_escape_the_script_element() -> None:
    view = project_profile_metadata(
        context_for(profile_view(display_name=HOSTILE_TEXT, bio_short=HOSTILE_TEXT)),
        page_url=PAGE_URL,
    )

    assert view.json_ld is not None
    for character in ("<", ">", "&", "\u2028", "\u2029"):
        assert character not in view.json_ld
    entity = main_entity_of(view)
    assert entity["name"] == HOSTILE_TEXT
    assert entity["description"] == HOSTILE_TEXT

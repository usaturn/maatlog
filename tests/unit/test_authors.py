"""Unit coverage for the author profile data model and its validation."""

from __future__ import annotations

import pytest

from maatlog.authors import (
    CONFIG_INVALID_CODE,
    AuthorLink,
    AuthorProfile,
    validate_author_profile,
)
from maatlog.errors import Diagnostic

FIELD = "maatlog_author_profiles.alice"


def test_validate_author_profile_normalizes_type_and_fills_label() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(
        FIELD, {"links": [{"type": "GitHub", "url": "https://github.com/alice"}]}, diagnostics
    )

    assert diagnostics == []
    assert profile is not None
    assert profile.links == (AuthorLink(type="github", url="https://github.com/alice", label="GitHub", icon="github"),)


def test_validate_author_profile_keeps_explicit_label() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(
        FIELD,
        {"links": [{"type": "x", "url": "https://x.com/alice", "label": "@alice"}]},
        diagnostics,
    )

    assert diagnostics == []
    assert profile is not None
    assert profile.links[0].label == "@alice"
    assert profile.links[0].icon == "x"


def test_validate_author_profile_falls_back_for_unknown_type() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(
        FIELD,
        {"links": [{"type": "Mastodon", "url": "https://example.social/@alice"}]},
        diagnostics,
    )

    assert diagnostics == []
    assert profile is not None
    assert profile.links[0].icon == "link"
    assert profile.links[0].label == "mastodon"


def test_validate_author_profile_uses_generic_icon_for_linkedin() -> None:
    """LinkedIn のブランドロゴは同梱しない。ラベルはテキストで補う。"""
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(
        FIELD,
        {"links": [{"type": "linkedin", "url": "https://www.linkedin.com/in/alice"}]},
        diagnostics,
    )

    assert diagnostics == []
    assert profile is not None
    assert profile.links[0].label == "LinkedIn"
    assert profile.links[0].icon == "link"


def test_validate_author_profile_preserves_link_order() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(
        FIELD,
        {
            "links": [
                {"type": "website", "url": "https://example.com"},
                {"type": "rss", "url": "https://example.com/atom.xml"},
            ]
        },
        diagnostics,
    )

    assert diagnostics == []
    assert profile is not None
    assert [link.type for link in profile.links] == ["website", "rss"]
    assert [link.icon for link in profile.links] == ["website", "rss"]


@pytest.mark.parametrize(
    "link",
    [
        {"url": "https://example.com"},
        {"type": "github"},
        {"type": "", "url": "https://example.com"},
        {"type": "   ", "url": "https://example.com"},
        {"type": 1, "url": "https://example.com"},
        {"type": "github", "url": ""},
        {"type": "github", "url": "javascript:alert(1)"},
        {"type": "github", "url": "/alice"},
        {"type": "github", "url": None},
        {"type": "github", "url": "https://example.com", "label": "  "},
        {"type": "github", "url": "https://example.com", "label": 1},
        {"type": "github", "url": "https://example.com", "extra": "x"},
    ],
)
def test_validate_author_profile_reports_link_invalid(link: dict[str, object]) -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, {"links": [link]}, diagnostics)

    assert result is None
    assert {item.code for item in diagnostics} == {"maatlog.author.link-invalid"}


def test_validate_author_profile_collects_every_diagnostic() -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(
        FIELD,
        {"links": [{"type": "github"}, {"type": "x", "url": "/alice"}]},
        diagnostics,
    )

    assert result is None
    assert [item.field for item in diagnostics] == [
        "maatlog_author_profiles.alice.links[0].url",
        "maatlog_author_profiles.alice.links[1].url",
    ]


def test_validate_author_profile_rejects_non_mapping_link() -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, {"links": ["https://example.com"]}, diagnostics)

    assert result is None
    assert [item.code for item in diagnostics] == ["maatlog.author.link-invalid"]


def test_validate_author_profile_rejects_unknown_profile_key() -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, {"bio": "x"}, diagnostics)

    assert result is None
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"]


@pytest.mark.parametrize("value", ["links", 1, ["https://example.com"], None])
def test_validate_author_profile_rejects_non_mapping_profile(value: object) -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, value, diagnostics)

    assert result is None
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"]


@pytest.mark.parametrize("value", ["https://example.com", 1, {"type": "github"}])
def test_validate_author_profile_rejects_non_sequence_links(value: object) -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, {"links": value}, diagnostics)

    assert result is None
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"]


def test_validate_author_profile_allows_missing_links() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, {}, diagnostics)

    assert diagnostics == []
    assert profile == AuthorProfile(links=())


def test_author_link_is_frozen() -> None:
    link = AuthorLink(type="github", url="https://github.com/alice", label="GitHub", icon="github")

    with pytest.raises(ValueError):
        link.type = "x"  # pyright: ignore[reportAttributeAccessIssue]


FULL_PROFILE = {
    "role": "Editor & Developer",
    "avatar": "authors/alice.png",
    "bio_short": "Python / Cloud / Sphinx developer.",
    "interests": ["Python", "Cloud", "Sphinx"],
    "links": [{"type": "github", "url": "https://github.com/alice"}],
    "featured_posts": ["one", "two"],
    "about_docname": "authors/alice",
}


def test_validate_author_profile_accepts_every_key() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, FULL_PROFILE, diagnostics)

    assert diagnostics == []
    assert profile is not None
    assert profile.role == "Editor & Developer"
    assert profile.avatar == "authors/alice.png"
    assert profile.bio_short == "Python / Cloud / Sphinx developer."
    assert profile.interests == ("Python", "Cloud", "Sphinx")
    assert profile.featured_posts == ("one", "two")
    assert profile.about_docname == "authors/alice"


def test_validate_author_profile_defaults_every_optional_key() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, {"links": []}, diagnostics)

    assert diagnostics == []
    assert profile == AuthorProfile()


def test_validate_author_profile_strips_optional_text() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, {"role": "  Editor  "}, diagnostics)

    assert diagnostics == []
    assert profile is not None
    assert profile.role == "Editor"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("role", ""),
        ("role", 1),
        ("avatar", "   "),
        ("bio_short", []),
        ("interests", "Python"),
        ("interests", [""]),
        ("interests", [1]),
        ("featured_posts", "one"),
        ("featured_posts", [""]),
        ("about_docname", "/authors/alice"),
        ("about_docname", "authors/../alice"),
        ("about_docname", ""),
    ],
)
def test_validate_author_profile_rejects_malformed_values(key: str, value: object) -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, {key: value}, diagnostics)

    assert profile is None
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"]


def test_validate_author_profile_rejects_duplicate_featured_posts() -> None:
    """同一 slug を重複設定した設定ミスは diagnostic で弾く（L-1 / PR #137 review）。"""
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, {**FULL_PROFILE, "featured_posts": ["one", "two", "one"]}, diagnostics)

    assert profile is None
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"]
    assert diagnostics[0].field == f"{FIELD}.featured_posts"
    assert diagnostics[0].expected == "a sequence without duplicate slugs"


def test_validate_author_profile_still_rejects_unknown_keys() -> None:
    diagnostics: list[Diagnostic] = []

    profile = validate_author_profile(FIELD, {"nickname": "al"}, diagnostics)

    assert profile is None
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" authors/alice ", "authors/alice"),
        ("\nabout\n", "about"),
    ],
)
def test_validate_author_profile_trims_whitespace_about_docname(raw: str, expected: str) -> None:
    """前後空白は正規化して受け付け、about-unknown に落ちる前の紛らわしさを消す。"""
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, {"about_docname": raw}, diagnostics)

    assert result is not None
    assert result.about_docname == expected
    assert diagnostics == []


@pytest.mark.parametrize(
    "raw",
    [" ", "   ", "\t"],
)
def test_validate_author_profile_rejects_blank_about_docname(raw: str) -> None:
    diagnostics: list[Diagnostic] = []

    result = validate_author_profile(FIELD, {"about_docname": raw}, diagnostics)

    assert result is None
    assert [item.code for item in diagnostics] == [CONFIG_INVALID_CODE]

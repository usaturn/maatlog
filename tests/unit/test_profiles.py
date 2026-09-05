"""Unit coverage for author profile statistics, initials, and cross-references."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from maatlog.authors import AuthorProfile
from maatlog.config import TaxonomyAxis
from maatlog.errors import MaatlogBuildError
from maatlog.model import Post, PublicationStatus
from maatlog.profiles import author_initials, author_stats, resolve_profiles
from maatlog.taxonomy import DomainIndex

TOKYO = ZoneInfo("Asia/Tokyo")
UTC_ZONE = ZoneInfo("UTC")


def make_post(slug: str, *, authors: tuple[str, ...], published_at: datetime) -> Post:
    return Post(
        docname=slug,
        source_path=f"{slug}.md",
        title=slug.title(),
        slug=slug,
        published_at=published_at,
        expires_at=None,
        tags=(),
        categories=(),
        authors=authors,
        excerpt=None,
        image_uri=None,
        canonical_url=None,
        external_url=None,
        status=PublicationStatus.PUBLISHED,
    )


PUBLISHED = (
    make_post("newest", authors=("alice",), published_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC)),
    make_post("middle", authors=("alice", "bob"), published_at=datetime(2025, 5, 1, 9, 0, tzinfo=UTC)),
    make_post("oldest", authors=("bob",), published_at=datetime(2024, 1, 1, 9, 0, tzinfo=UTC)),
)


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("Alice Anderson", "AA"),
        ("alice anderson", "AA"),
        ("Alice", "A"),
        ("Alice B. Anderson", "AB"),
        ("   ", ""),
        ("", ""),
    ],
)
def test_author_initials(display_name: str, expected: str) -> None:
    assert author_initials(display_name) == expected


def test_author_stats_counts_only_that_author() -> None:
    stats = author_stats(PUBLISHED, "alice", timezone=UTC_ZONE)

    assert stats.post_count == 2
    assert stats.writing_since == 2025
    assert stats.latest_post == datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def test_author_stats_uses_configured_timezone_for_writing_since() -> None:
    """2024-12-31T20:00Z は Asia/Tokyo では 2025-01-01。"""
    posts = (make_post("edge", authors=("alice",), published_at=datetime(2024, 12, 31, 20, 0, tzinfo=UTC)),)

    assert author_stats(posts, "alice", timezone=TOKYO).writing_since == 2025
    assert author_stats(posts, "alice", timezone=UTC_ZONE).writing_since == 2024


def test_author_stats_uses_configured_timezone_for_latest_post() -> None:
    """2024-12-31T20:00Z は Asia/Tokyo では 2025-01-01。月アーカイブの所属月と一致させる。"""
    posts = (make_post("edge", authors=("alice",), published_at=datetime(2024, 12, 31, 20, 0, tzinfo=UTC)),)

    tokyo = author_stats(posts, "alice", timezone=TOKYO).latest_post
    utc = author_stats(posts, "alice", timezone=UTC_ZONE).latest_post
    assert tokyo is not None and tokyo.strftime("%Y-%m-%d") == "2025-01-01"
    assert utc is not None and utc.strftime("%Y-%m-%d") == "2024-12-31"


def test_author_stats_is_empty_for_an_author_without_published_posts() -> None:
    stats = author_stats(PUBLISHED, "carol", timezone=UTC_ZONE)

    assert stats.post_count == 0
    assert stats.writing_since is None
    assert stats.latest_post is None


INDEX = DomainIndex(
    docname_by_slug={post.slug: post.docname for post in PUBLISHED},
    members={
        TaxonomyAxis.AUTHOR: {"alice": ("newest", "middle"), "bob": ("middle", "oldest")},
        TaxonomyAxis.TAG: {},
        TaxonomyAxis.CATEGORY: {},
        TaxonomyAxis.MONTH: {},
    },
    labels={
        TaxonomyAxis.AUTHOR: {"alice": "Alice", "bob": "Bob"},
        TaxonomyAxis.TAG: {},
        TaxonomyAxis.CATEGORY: {},
        TaxonomyAxis.MONTH: {},
    },
    published=PUBLISHED,
)
AUTHORS: Mapping[str, str] = {"alice": "Alice Anderson", "bob": "Bob"}


def codes_of(error: MaatlogBuildError) -> list[str]:
    return [item.code for item in error.diagnostics]


def test_resolve_profiles_accepts_a_consistent_profile(tmp_path: Path) -> None:
    (tmp_path / "authors").mkdir()
    (tmp_path / "authors" / "alice.png").write_bytes(b"png")

    resolved = resolve_profiles(
        {
            "alice": AuthorProfile(
                avatar="authors/alice.png", featured_posts=("newest",), about_docname="authors/alice"
            )
        },
        authors=AUTHORS,
        index=INDEX,
        known_docnames={"index", "authors/alice"},
        srcdir=tmp_path,
    )

    assert resolved.avatars == {"alice": "authors/alice.png"}


def test_resolve_profiles_rejects_an_author_absent_from_maatlog_authors(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"carol": AuthorProfile()},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert codes_of(excinfo.value) == ["maatlog.author.profile-unknown"]


def test_resolve_profiles_skips_the_author_check_when_authors_is_unset(tmp_path: Path) -> None:
    resolved = resolve_profiles(
        {"carol": AuthorProfile()},
        authors=None,
        index=INDEX,
        known_docnames={"index"},
        srcdir=tmp_path,
    )

    assert resolved.avatars == {}


def test_resolve_profiles_rejects_an_unknown_featured_slug(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"alice": AuthorProfile(featured_posts=("nope",))},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert codes_of(excinfo.value) == ["maatlog.author.featured-unknown"]


def test_resolve_profiles_rejects_a_featured_post_of_another_author(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"alice": AuthorProfile(featured_posts=("oldest",))},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert codes_of(excinfo.value) == ["maatlog.author.featured-foreign"]


def test_resolve_profiles_rejects_an_unknown_about_docname(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"alice": AuthorProfile(about_docname="authors/missing")},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert codes_of(excinfo.value) == ["maatlog.author.about-unknown"]


def test_resolve_profiles_rejects_a_missing_avatar(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"alice": AuthorProfile(avatar="authors/absent.png")},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert codes_of(excinfo.value) == ["maatlog.image.missing"]


def test_resolve_profiles_rejects_an_avatar_escaping_the_source_directory(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"alice": AuthorProfile(avatar="../outside.png")},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert codes_of(excinfo.value) == ["maatlog.image.invalid"]


def test_resolve_profiles_reports_every_problem_at_once(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        resolve_profiles(
            {"alice": AuthorProfile(featured_posts=("nope",), about_docname="authors/missing")},
            authors=AUTHORS,
            index=INDEX,
            known_docnames={"index"},
            srcdir=tmp_path,
        )

    assert sorted(codes_of(excinfo.value)) == [
        "maatlog.author.about-unknown",
        "maatlog.author.featured-unknown",
    ]


class _StubBuilder:
    """image_url_for が builder.images を見つけられない最小のスタブ。"""

    images = None
    imagedir = "_images"

    def get_target_uri(self, docname: str) -> str:
        return f"{docname}.html"


def _stub_builder() -> Any:
    return _StubBuilder()


def test_author_summary_views_keep_the_given_order() -> None:
    from maatlog.profiles import author_summary_views
    from maatlog.views import TaxonomyLinkView

    summaries = author_summary_views(
        _stub_builder(),
        authors=(
            TaxonomyLinkView(id="bob", label="Bob Brown", url="blog/author/bob.html"),
            TaxonomyLinkView(id="alice", label="Alice Anderson", url="blog/author/alice.html"),
        ),
        profiles={},
        avatars={},
        from_docname="post",
    )

    assert [summary.slug for summary in summaries] == ["bob", "alice"]
    assert [summary.display_name for summary in summaries] == ["Bob Brown", "Alice Anderson"]


def test_author_summary_view_falls_back_to_initials_without_an_avatar() -> None:
    from maatlog.profiles import author_summary_views
    from maatlog.views import TaxonomyLinkView

    (summary,) = author_summary_views(
        _stub_builder(),
        authors=(TaxonomyLinkView(id="alice", label="Alice Anderson", url="a.html"),),
        profiles={},
        avatars={},
        from_docname="post",
    )

    assert summary.avatar_url is None
    assert summary.initials == "AA"
    assert summary.bio_short is None
    assert summary.links == ()
    assert summary.profile_url == "a.html"


def test_author_summary_view_carries_the_configured_profile_fields() -> None:
    from maatlog.authors import AuthorLink, AuthorProfile
    from maatlog.profiles import author_summary_views
    from maatlog.views import TaxonomyLinkView

    profile = AuthorProfile(
        bio_short="Python developer.",
        links=(AuthorLink(type="github", url="https://github.com/x", label="GitHub", icon="github"),),
    )

    (summary,) = author_summary_views(
        _stub_builder(),
        authors=(TaxonomyLinkView(id="alice", label="Alice Anderson", url="a.html"),),
        profiles={"alice": profile},
        avatars={"alice": "authors/alice.png"},
        from_docname="post",
    )

    assert summary.bio_short == "Python developer."
    assert [link.icon for link in summary.links] == ["github"]
    assert summary.avatar_url is not None


def test_author_summary_view_keeps_an_empty_profile_url_for_an_author_without_posts() -> None:
    from maatlog.profiles import author_summary_views
    from maatlog.views import TaxonomyLinkView

    (summary,) = author_summary_views(
        _stub_builder(),
        authors=(TaxonomyLinkView(id="carol", label="Carol", url=""),),
        profiles={},
        avatars={},
        from_docname="post",
    )

    assert summary.profile_url == ""

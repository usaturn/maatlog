from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maatlog.config import MaatlogConfig, TaxonomyAxis
from maatlog.errors import MaatlogBuildError
from maatlog.model import Post, PublicationStatus
from maatlog.taxonomy import DomainIndex, build_domain_index, published_sort_key


def test_domain_index_is_stable_and_uses_site_timezone(posts: Mapping[str, Post], config: MaatlogConfig) -> None:
    index = build_domain_index(dict(reversed(list(posts.items()))), config)

    assert [post.slug for post in index.published] == ["late-utc", "new", "same-a", "same-b", "old"]
    assert index.members[TaxonomyAxis.MONTH]["2026-08"] == ("late-utc",)
    assert index.members[TaxonomyAxis.MONTH]["2026-07"] == ("new", "same-a", "same-b", "old")


def test_domain_index_ignores_input_mapping_order(posts: Mapping[str, Post], config: MaatlogConfig) -> None:
    forward = build_domain_index(dict(posts), config)
    reverse = build_domain_index(dict(reversed(list(posts.items()))), config)

    assert forward == reverse
    assert list(forward.members[TaxonomyAxis.TAG]) == sorted(forward.members[TaxonomyAxis.TAG])
    assert list(forward.labels[TaxonomyAxis.TAG]) == sorted(forward.labels[TaxonomyAxis.TAG])


def test_duplicate_slug_reports_all_locations(config: MaatlogConfig) -> None:
    with pytest.raises(MaatlogBuildError) as error:
        build_domain_index(posts_with_duplicate_draft_and_public(), config)

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.slug.duplicate"
    assert "draft.rst" in diagnostic.message
    assert "public.md" in diagnostic.message


def test_published_snapshot_excludes_non_published(config: MaatlogConfig) -> None:
    posts = {
        "draft": _post(
            docname="draft",
            source_path="draft.rst",
            slug="draft",
            published_at=None,
            status=PublicationStatus.DRAFT,
            tags=("hidden",),
        ),
        "scheduled": _post(
            docname="scheduled",
            source_path="scheduled.rst",
            slug="scheduled",
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
            status=PublicationStatus.SCHEDULED,
            tags=("hidden",),
        ),
        "expired": _post(
            docname="expired",
            source_path="expired.rst",
            slug="expired",
            published_at=datetime(2026, 6, 1, tzinfo=UTC),
            expires_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.EXPIRED,
            tags=("hidden",),
        ),
        "live": _post(
            docname="live",
            source_path="live.rst",
            slug="live",
            published_at=datetime(2026, 7, 15, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("visible",),
        ),
    }

    index = build_domain_index(posts, config)

    assert [post.slug for post in index.published] == ["live"]
    assert index.members[TaxonomyAxis.TAG] == {"visible": ("live",)}
    assert index.labels[TaxonomyAxis.TAG] == {"visible": "visible"}
    assert "hidden" not in index.members[TaxonomyAxis.TAG]
    assert index.docname_by_slug == {
        "draft": "draft",
        "expired": "expired",
        "live": "live",
        "scheduled": "scheduled",
    }


def test_auto_register_uses_id_as_label_for_open_taxonomies(config: MaatlogConfig) -> None:
    posts = {
        "a": _post(
            docname="a",
            source_path="a.rst",
            slug="a",
            published_at=datetime(2026, 7, 2, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("python", "sphinx"),
            categories=("engineering",),
            authors=("alice",),
        ),
        "b": _post(
            docname="b",
            source_path="b.rst",
            slug="b",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("sphinx",),
            categories=("news",),
            authors=("bob", "alice"),
        ),
    }

    index = build_domain_index(posts, config)

    assert index.members[TaxonomyAxis.TAG] == {"python": ("a",), "sphinx": ("a", "b")}
    assert index.labels[TaxonomyAxis.TAG] == {"python": "python", "sphinx": "sphinx"}
    assert index.members[TaxonomyAxis.CATEGORY] == {"engineering": ("a",), "news": ("b",)}
    assert index.labels[TaxonomyAxis.AUTHOR] == {"alice": "alice", "bob": "bob"}
    assert index.members[TaxonomyAxis.AUTHOR]["alice"] == ("a", "b")


def test_allowlist_uses_configured_labels_and_only_used_ids() -> None:
    config = MaatlogConfig.from_values(
        {
            "maatlog_timezone": "UTC",
            "maatlog_tags": {"sphinx": "Sphinx", "unused": "Unused"},
            "maatlog_categories": {"engineering": "Engineering"},
            "maatlog_authors": {"alice": "Alice"},
        }
    )
    posts = {
        "post": _post(
            docname="post",
            source_path="post.rst",
            slug="post",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("sphinx",),
            categories=("engineering",),
            authors=("alice",),
        )
    }

    index = build_domain_index(posts, config)

    assert index.labels[TaxonomyAxis.TAG] == {"sphinx": "Sphinx"}
    assert "unused" not in index.members[TaxonomyAxis.TAG]
    assert index.labels[TaxonomyAxis.CATEGORY] == {"engineering": "Engineering"}
    assert index.labels[TaxonomyAxis.AUTHOR] == {"alice": "Alice"}


def test_allowlist_rejects_undefined_taxonomy_ids() -> None:
    config = MaatlogConfig.from_values(
        {
            "maatlog_timezone": "UTC",
            "maatlog_tags": {"known": "Known"},
        }
    )
    posts = {
        "post": _post(
            docname="post",
            source_path="post.rst",
            slug="post",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("unknown",),
        )
    }

    with pytest.raises(MaatlogBuildError) as error:
        build_domain_index(posts, config)

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.taxonomy.undefined"
    assert diagnostic.value == repr("unknown")


def test_month_axis_uses_site_timezone_boundary() -> None:
    config = MaatlogConfig.from_values({"maatlog_timezone": "Asia/Tokyo"})
    posts = {
        "late-utc": _post(
            docname="late-utc",
            source_path="late-utc.rst",
            slug="late-utc",
            # 2026-08-01 01:00 in Asia/Tokyo
            published_at=datetime(2026, 7, 31, 16, 0, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
        ),
        "still-july": _post(
            docname="still-july",
            source_path="still-july.rst",
            slug="still-july",
            # 2026-07-31 23:00 in Asia/Tokyo
            published_at=datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
        ),
    }

    index = build_domain_index(posts, config)

    assert index.members[TaxonomyAxis.MONTH] == {
        "2026-07": ("still-july",),
        "2026-08": ("late-utc",),
    }
    assert index.labels[TaxonomyAxis.MONTH] == {
        "2026-07": "2026-07",
        "2026-08": "2026-08",
    }


def test_published_sort_key_orders_newest_then_slug_then_docname() -> None:
    earlier = _post(
        docname="z",
        source_path="z.rst",
        slug="z",
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        status=PublicationStatus.PUBLISHED,
    )
    later = _post(
        docname="a",
        source_path="a.rst",
        slug="a",
        published_at=datetime(2026, 7, 2, tzinfo=UTC),
        status=PublicationStatus.PUBLISHED,
    )
    same_slug_first = _post(
        docname="doc-a",
        source_path="doc-a.rst",
        slug="same",
        published_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        status=PublicationStatus.PUBLISHED,
    )
    same_slug_second = _post(
        docname="doc-b",
        source_path="doc-b.rst",
        slug="same",
        published_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        status=PublicationStatus.PUBLISHED,
    )

    ordered = sorted(
        [earlier, later, same_slug_second, same_slug_first],
        key=published_sort_key,
    )
    assert [post.docname for post in ordered] == ["a", "doc-a", "doc-b", "z"]


def test_domain_index_is_frozen_pydantic_model(posts: Mapping[str, Post], config: MaatlogConfig) -> None:
    index = build_domain_index(posts, config)

    assert isinstance(index, DomainIndex)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        field_name = "published"
        setattr(index, field_name, ())


@pytest.fixture
def config() -> MaatlogConfig:
    return MaatlogConfig.from_values({"maatlog_timezone": "Asia/Tokyo"})


@pytest.fixture
def posts() -> dict[str, Post]:
    same_time = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    return {
        "old": _post(
            docname="old",
            source_path="old.rst",
            slug="old",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("release",),
        ),
        "same-b": _post(
            docname="same-b",
            source_path="same-b.rst",
            slug="same-b",
            published_at=same_time,
            status=PublicationStatus.PUBLISHED,
            tags=("release",),
        ),
        "same-a": _post(
            docname="same-a",
            source_path="same-a.rst",
            slug="same-a",
            published_at=same_time,
            status=PublicationStatus.PUBLISHED,
            tags=("release",),
        ),
        "new": _post(
            docname="new",
            source_path="new.rst",
            slug="new",
            published_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("release",),
        ),
        "late-utc": _post(
            docname="late-utc",
            source_path="late-utc.rst",
            slug="late-utc",
            # 2026-08-01 01:00 Asia/Tokyo
            published_at=datetime(2026, 7, 31, 16, 0, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
            tags=("timezone",),
        ),
        "draft": _post(
            docname="draft",
            source_path="draft.rst",
            slug="draft-only",
            published_at=None,
            status=PublicationStatus.DRAFT,
            tags=("release",),
        ),
    }


def posts_with_duplicate_draft_and_public() -> dict[str, Post]:
    return {
        "draft": _post(
            docname="draft",
            source_path="posts/draft.rst",
            slug="shared",
            published_at=None,
            status=PublicationStatus.DRAFT,
        ),
        "public": _post(
            docname="public",
            source_path="posts/public.md",
            slug="shared",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
        ),
    }


def _post(
    *,
    docname: str,
    source_path: str,
    slug: str,
    published_at: datetime | None,
    status: PublicationStatus,
    expires_at: datetime | None = None,
    tags: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
    authors: tuple[str, ...] = (),
    title: str | None = None,
) -> Post:
    return Post(
        docname=docname,
        source_path=source_path,
        title=title or slug,
        slug=slug,
        published_at=published_at,
        expires_at=expires_at,
        tags=tags,
        categories=categories,
        authors=authors,
        excerpt=None,
        image_uri=None,
        canonical_url=None,
        external_url=None,
        status=status,
    )

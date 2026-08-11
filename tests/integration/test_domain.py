from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import SphinxFactory

from maatlog.config import MaatlogConfig, TaxonomyAxis
from maatlog.domain import MaatlogDomain
from maatlog.errors import MaatlogBuildError
from maatlog.model import Post, PublicationStatus
from maatlog.taxonomy import build_domain_index


def test_domain_published_posts_returns_rebuilt_snapshot(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "old.rst": _rst_post(slug="old", published_at="2026-07-01T00:00:00Z"),
            "new.rst": _rst_post(slug="new", published_at="2026-07-20T00:00:00Z"),
            "draft.rst": _rst_post(slug="draft", published_at=None),
        },
        config={"maatlog_timezone": "UTC"},
    )
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    config = MaatlogConfig.from_sphinx(app.config)

    # env-updated finalizes the index during build
    assert [post.slug for post in domain.published_posts()] == ["new", "old"]
    index = domain.rebuild_index(config)

    assert domain.published_posts() == index.published
    assert domain.data["index"] is index
    assert index.members[TaxonomyAxis.MONTH] == {"2026-07": ("new", "old")}


def test_domain_index_matches_direct_build(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "alpha.rst": _rst_post(
                slug="alpha",
                published_at="2026-07-10T00:00:00Z",
                tags="sphinx, python",
                categories="engineering",
                authors="alice",
            ),
            "beta.rst": _rst_post(
                slug="beta",
                published_at="2026-07-11T00:00:00Z",
                tags="sphinx",
                categories="news",
                authors="bob",
            ),
            "draft.rst": _rst_post(slug="draft", published_at=None, tags="hidden"),
        },
        config={"maatlog_timezone": "UTC"},
    )
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    config = MaatlogConfig.from_sphinx(app.config)
    posts = domain.data["posts_by_docname"]

    expected = build_domain_index(posts, config)
    actual = domain.rebuild_index(config)

    assert actual == expected
    assert domain.published_posts() == expected.published
    assert "draft" not in {post.slug for post in domain.published_posts()}
    assert actual.members[TaxonomyAxis.TAG]["sphinx"] == ("beta", "alpha")


def test_rebuild_index_includes_all_slugs_including_drafts(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "live.rst": _rst_post(slug="live", published_at="2026-07-01T00:00:00Z"),
            "draft.rst": _rst_post(slug="draft-slug", published_at=None),
        }
    )
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    index = domain.rebuild_index(MaatlogConfig.from_sphinx(app.config))

    assert index.docname_by_slug == {"draft-slug": "draft", "live": "live"}


def test_clear_doc_removes_post_before_reindex(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "keep.rst": _rst_post(slug="keep", published_at="2026-07-01T00:00:00Z"),
            "drop.rst": _rst_post(slug="drop", published_at="2026-07-02T00:00:00Z"),
        }
    )
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    config = MaatlogConfig.from_sphinx(app.config)
    domain.clear_doc("drop")
    index = domain.rebuild_index(config)

    assert "drop" not in domain.data["posts_by_docname"]
    assert [post.slug for post in domain.published_posts()] == ["keep"]
    assert "drop" not in index.docname_by_slug


def test_purge_removes_post_before_reindex() -> None:
    domain = _empty_domain()
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC"})
    post = _post(docname="drop", slug="drop", published_at=datetime(2026, 7, 2, tzinfo=UTC))
    build_time = datetime(2026, 8, 1, tzinfo=UTC)

    domain.note_post(post)
    domain.clear_doc(post.docname)
    domain.finalize(config, build_time=build_time, known_docnames=set())

    assert post.docname not in domain.data["posts_by_docname"]
    assert domain.published_posts() == ()
    assert domain.data["index"] is not None
    assert domain.data["index"].docname_by_slug == {}


def test_merge_rejects_different_values_for_same_docname() -> None:
    domain = _empty_domain()
    worker = _empty_domain()
    domain.note_post(_post(docname="post", slug="one", published_at=datetime(2026, 7, 1, tzinfo=UTC)))
    worker.note_post(_post(docname="post", slug="two", published_at=datetime(2026, 7, 1, tzinfo=UTC)))

    with pytest.raises(MaatlogBuildError, match="maatlog.domain.merge-conflict") as error:
        domain.merge(worker.data, {"post"})

    assert error.value.diagnostics[0].code == "maatlog.domain.merge-conflict"
    assert error.value.diagnostics[0].value == repr("post")


def test_merge_identical_values_is_idempotent() -> None:
    domain = _empty_domain()
    worker = _empty_domain()
    post = _post(docname="post", slug="shared", published_at=datetime(2026, 7, 1, tzinfo=UTC))
    domain.note_post(post)
    worker.note_post(post)

    domain.merge(worker.data, {"post"})
    domain.merge(worker.data, {"post"})

    assert domain.data["posts_by_docname"]["post"] == post
    assert domain.data["index"] is None


def test_merge_imports_worker_only_docnames() -> None:
    domain = _empty_domain()
    worker = _empty_domain()
    keep = _post(docname="keep", slug="keep", published_at=datetime(2026, 7, 1, tzinfo=UTC))
    imported = _post(docname="imported", slug="imported", published_at=datetime(2026, 7, 2, tzinfo=UTC))
    ignored = _post(docname="ignored", slug="ignored", published_at=datetime(2026, 7, 3, tzinfo=UTC))
    domain.note_post(keep)
    worker.note_post(imported)
    worker.note_post(ignored)

    domain.merge(worker.data, {"imported"})

    assert set(domain.data["posts_by_docname"]) == {"keep", "imported"}
    assert domain.data["posts_by_docname"]["imported"] == imported


def test_finalize_builds_published_snapshot() -> None:
    domain = _empty_domain()
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC"})
    build_time = datetime(2026, 8, 1, tzinfo=UTC)
    domain.note_post(
        _post(
            docname="old",
            slug="old",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
        )
    )
    domain.note_post(
        _post(
            docname="new",
            slug="new",
            published_at=datetime(2026, 7, 20, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
        )
    )
    domain.note_post(
        _post(
            docname="draft",
            slug="draft",
            published_at=None,
            status=PublicationStatus.DRAFT,
        )
    )

    index = domain.finalize(config, build_time=build_time, known_docnames={"old", "new", "draft"})

    assert [post.slug for post in domain.published_posts()] == ["new", "old"]
    assert domain.published_posts() == index.published
    assert domain.data["index"] is index
    assert index.docname_by_slug == {"draft": "draft", "new": "new", "old": "old"}
    assert "blog" in domain.data["generated_docnames"]


def test_note_post_and_clear_doc_invalidate_stored_index() -> None:
    domain = _empty_domain()
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC"})
    build_time = datetime(2026, 8, 1, tzinfo=UTC)
    first = _post(docname="a", slug="a", published_at=datetime(2026, 7, 1, tzinfo=UTC))
    second = _post(docname="b", slug="b", published_at=datetime(2026, 7, 2, tzinfo=UTC))

    domain.note_post(first)
    domain.finalize(config, build_time=build_time, known_docnames={"a"})
    assert domain.data["index"] is not None

    domain.note_post(second)
    assert domain.data["index"] is None

    domain.finalize(config, build_time=build_time, known_docnames={"a", "b"})
    assert domain.data["index"] is not None

    domain.clear_doc("a")
    assert domain.data["index"] is None


def test_finalize_recomputes_publication_status_with_build_time() -> None:
    domain = _empty_domain()
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC"})
    domain.note_post(
        _post(
            docname="scheduled",
            slug="future",
            published_at=datetime(2026, 8, 10, tzinfo=UTC),
            status=PublicationStatus.SCHEDULED,
        )
    )

    domain.finalize(
        config,
        build_time=datetime(2026, 8, 1, tzinfo=UTC),
        known_docnames={"scheduled"},
    )
    assert domain.data["posts_by_docname"]["scheduled"].status is PublicationStatus.SCHEDULED
    assert domain.published_posts() == ()

    domain.finalize(
        config,
        build_time=datetime(2026, 8, 15, tzinfo=UTC),
        known_docnames={"scheduled"},
    )
    assert domain.data["posts_by_docname"]["scheduled"].status is PublicationStatus.PUBLISHED
    assert [post.slug for post in domain.published_posts()] == ["future"]


def test_finalize_rejects_generated_docname_conflict() -> None:
    domain = _empty_domain()
    config = MaatlogConfig.from_values({"maatlog_timezone": "UTC", "maatlog_archive_docname": "blog"})
    domain.note_post(
        _post(
            docname="post",
            slug="one",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            status=PublicationStatus.PUBLISHED,
        )
    )

    with pytest.raises(MaatlogBuildError, match="maatlog.generated-docname.conflict") as error:
        domain.finalize(
            config,
            build_time=datetime(2026, 8, 1, tzinfo=UTC),
            known_docnames={"blog", "post"},
        )

    assert error.value.diagnostics[0].value == "blog"


def test_finalize_runs_during_sphinx_build(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "live.rst": _rst_post(slug="live", published_at="2026-07-01T00:00:00Z"),
            "draft.rst": _rst_post(slug="draft", published_at=None),
        },
        config={"maatlog_timezone": "UTC"},
    )
    app.build()

    domain = app.env.get_domain("maatlog")
    assert isinstance(domain, MaatlogDomain)
    assert domain.data["index"] is not None
    assert [post.slug for post in domain.published_posts()] == ["live"]


class _FakeEnv:
    def __init__(self) -> None:
        self.domaindata: dict[str, dict[str, Any]] = {}


def _empty_domain() -> MaatlogDomain:
    return MaatlogDomain(_FakeEnv())  # type: ignore[arg-type]


def _post(
    *,
    docname: str,
    slug: str,
    published_at: datetime | None,
    status: PublicationStatus | None = None,
) -> Post:
    if status is None:
        status = PublicationStatus.DRAFT if published_at is None else PublicationStatus.PUBLISHED
    return Post(
        docname=docname,
        source_path=f"{docname}.rst",
        title=slug,
        slug=slug,
        published_at=published_at,
        expires_at=None,
        tags=(),
        categories=(),
        authors=(),
        excerpt=None,
        image_uri=None,
        canonical_url=None,
        external_url=None,
        status=status,
    )


def _rst_post(
    *,
    slug: str,
    published_at: str | None,
    tags: str = "",
    categories: str = "",
    authors: str = "",
) -> str:
    lines = [":maatlog-post: true", f":maatlog-slug: {slug}"]
    if published_at is not None:
        lines.append(f":maatlog-published-at: {published_at}")
    if tags:
        lines.append(f":maatlog-tags: {tags}")
    if categories:
        lines.append(f":maatlog-categories: {categories}")
    if authors:
        lines.append(f":maatlog-authors: {authors}")
    title = slug.replace("-", " ").title()
    lines.extend(["", title, "=" * len(title), ""])
    return "\n".join(lines)

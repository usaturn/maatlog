"""Incremental domain builds: add / change / delete match a clean rebuild."""

from __future__ import annotations

from conftest import ProjectFactory

from maatlog.model import PublicationStatus


def _rst_post(
    *,
    slug: str,
    published_at: str | None,
    tags: str = "",
    categories: str = "",
    authors: str = "",
    title: str | None = None,
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
    heading = title if title is not None else slug.replace("-", " ").title()
    lines.extend(["", heading, "=" * len(heading), "", f"Body for {slug}.", ""])
    return "\n".join(lines)


BASE_FILES = {
    "keep.rst": _rst_post(
        slug="keep",
        published_at="2026-07-01T00:00:00Z",
        tags="stable",
        categories="news",
        authors="alice",
    ),
    "removed-post.rst": _rst_post(
        slug="removed",
        published_at="2026-07-02T00:00:00Z",
        tags="gone",
        categories="news",
        authors="bob",
    ),
    "mutable.rst": _rst_post(
        slug="mutable",
        published_at="2026-07-03T00:00:00Z",
        tags="old-tag",
        categories="engineering",
        authors="alice",
    ),
    "draft.rst": _rst_post(slug="draft-only", published_at=None, tags="hidden"),
}

BASE_CONFIG = {"maatlog_timezone": "UTC"}


def test_incremental_delete_matches_clean_build(make_project: ProjectFactory) -> None:
    project = make_project(files=BASE_FILES, config=BASE_CONFIG)
    project.build(reuse_environment=False)

    project.remove("removed-post.rst")
    incremental = project.build(reuse_environment=True)
    clean = project.build(reuse_environment=False)

    assert incremental.domain_data("maatlog") == clean.domain_data("maatlog")
    snap = clean.domain_data("maatlog")
    assert "removed-post" not in snap.posts_by_docname
    assert "removed" not in snap.docname_by_slug
    assert set(snap.published_slugs) == {"mutable", "keep"}


def test_incremental_change_matches_clean_build(make_project: ProjectFactory) -> None:
    project = make_project(files=BASE_FILES, config=BASE_CONFIG)
    project.build(reuse_environment=False)

    project.write(
        "mutable.rst",
        _rst_post(
            slug="mutable",
            published_at="2026-07-20T00:00:00Z",
            tags="new-tag",
            categories="engineering",
            authors="carol",
            title="Mutable Updated",
        ),
    )
    incremental = project.build(reuse_environment=True)
    clean = project.build(reuse_environment=False)

    assert incremental.domain_data("maatlog") == clean.domain_data("maatlog")
    snap = clean.domain_data("maatlog")
    assert snap.posts_by_docname["mutable"].title == "Mutable Updated"
    assert snap.posts_by_docname["mutable"].tags == ("new-tag",)
    assert snap.posts_by_docname["mutable"].authors == ("carol",)
    assert snap.published_slugs[0] == "mutable"


def test_incremental_add_matches_clean_build(make_project: ProjectFactory) -> None:
    files = {k: v for k, v in BASE_FILES.items() if k != "removed-post.rst"}
    project = make_project(files=files, config=BASE_CONFIG)
    project.build(reuse_environment=False)

    project.write(
        "new-post.rst",
        _rst_post(
            slug="brand-new",
            published_at="2026-07-25T00:00:00Z",
            tags="fresh",
            categories="news",
            authors="dave",
        ),
    )
    incremental = project.build(reuse_environment=True)
    clean = project.build(reuse_environment=False)

    assert incremental.domain_data("maatlog") == clean.domain_data("maatlog")
    snap = clean.domain_data("maatlog")
    assert "new-post" in snap.posts_by_docname
    assert snap.posts_by_docname["new-post"].slug == "brand-new"
    assert "brand-new" in snap.published_slugs


def test_publication_status_recomputed_at_finalize_without_source_change(
    make_project: ProjectFactory,
) -> None:
    """With feeds disabled, a later SOURCE_DATE_EPOCH publishes a scheduled post.

    Status refresh must happen in finalize/rebuild_index, not via feed-driven
    force-outdated re-reads of unchanged sources.
    """
    # 2026-07-01T00:00:00Z — before the scheduled publication.
    before_epoch = "1782864000"
    # 2026-08-15T00:00:00Z — after the scheduled publication.
    after_epoch = "1786752000"
    files = {
        "scheduled.md": """---
maatlog-post: true
maatlog-slug: future-post
maatlog-published-at: 2026-08-01T12:00:00Z
---
# Future Post

Scheduled body.
""",
    }
    project = make_project(
        files=files,
        source_date_epoch=before_epoch,
        config={"maatlog_generate_feeds": False, "maatlog_timezone": "UTC"},
    )
    first = project.build(reuse_environment=False)
    first_post = first.domain_data("maatlog").posts_by_docname["scheduled"]
    assert first_post.status is PublicationStatus.SCHEDULED
    assert "future-post" not in first.domain_data("maatlog").published_slugs
    assert "Future Post" not in (project.outdir / "blog.html").read_text(encoding="utf-8")

    project.source_date_epoch = after_epoch
    second = project.build(reuse_environment=True)
    second_snap = second.domain_data("maatlog")
    assert second_snap.posts_by_docname["scheduled"].status is PublicationStatus.PUBLISHED
    assert "future-post" in second_snap.published_slugs
    assert "Future Post" in (project.outdir / "blog.html").read_text(encoding="utf-8")

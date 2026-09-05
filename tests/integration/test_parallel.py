"""Serial vs parallel domain equivalence and parallel-path smoke coverage."""

from __future__ import annotations

import pytest
from conftest import ProjectFactory
from sphinx.errors import SphinxError

from maatlog.errors import MaatlogBuildError
from tests.integration.test_author_profile import PNG_1X1


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
    lines.extend(["", title, "=" * len(title), "", f"Body for {slug}.", ""])
    return "\n".join(lines)


PARALLEL_FILES = {
    f"post-{i:02d}.rst": _rst_post(
        slug=f"slug-{i:02d}",
        published_at=f"2026-07-{(i % 28) + 1:02d}T00:00:00Z",
        tags="sphinx, python" if i % 2 == 0 else "ops",
        categories="engineering" if i % 3 else "news",
        authors="alice" if i % 2 == 0 else "bob",
    )
    for i in range(8)
}
PARALLEL_FILES["draft.rst"] = _rst_post(slug="draft-x", published_at=None, tags="hidden")
PARALLEL_FILES["listing.rst"] = "Listing\n=======\n\n.. maatlog:post-list::\n"
PARALLEL_CONFIG = {"maatlog_timezone": "UTC"}


def test_parallel_read_matches_serial(make_project: ProjectFactory) -> None:
    project = make_project(files=PARALLEL_FILES, config=PARALLEL_CONFIG)

    serial = project.build(parallel=1, reuse_environment=False)
    parallel = project.build(parallel=4, reuse_environment=False)

    assert parallel.domain_data("maatlog") == serial.domain_data("maatlog")
    snap = serial.domain_data("maatlog")
    assert len(snap.posts_by_docname) == 9  # 8 published + draft
    assert "draft-x" in snap.docname_by_slug
    assert "draft-x" not in snap.published_slugs
    assert len(snap.published_slugs) == 8


def test_parallel_read_matches_serial_j2(make_project: ProjectFactory) -> None:
    project = make_project(files=PARALLEL_FILES, config=PARALLEL_CONFIG)
    assert project.build(parallel=2, reuse_environment=False).domain_data("maatlog") == project.build(
        parallel=1, reuse_environment=False
    ).domain_data("maatlog")


def test_parallel_duplicate_slug_fails(make_project: ProjectFactory) -> None:
    files = {
        "public.rst": _rst_post(slug="shared", published_at="2026-07-01T00:00:00Z"),
        "draft.rst": _rst_post(slug="shared", published_at=None),
        "other.rst": _rst_post(slug="other", published_at="2026-07-02T00:00:00Z"),
    }
    project = make_project(files=files, config=PARALLEL_CONFIG)

    with pytest.raises((MaatlogBuildError, SphinxError)) as error:
        project.build(parallel=4, reuse_environment=False)

    text = str(error.value)
    assert "maatlog.slug.duplicate" in text or "shared" in text


def test_parallel_archive_cards_match_serial(make_project: ProjectFactory) -> None:
    """Archive DOM card order/slugs match between serial and parallel builds."""
    project = make_project(
        files=PARALLEL_FILES,
        config={**PARALLEL_CONFIG, "html_baseurl": "https://example.com/docs/"},
    )
    serial = project.build(parallel=1, reuse_environment=False)
    parallel = project.build(parallel=4, reuse_environment=False)

    for relative in ("blog.html", "blog/tag/sphinx.html", "blog/author/alice.html"):
        serial_page = serial.html(relative)
        parallel_page = parallel.html(relative)
        serial_slugs = [attrs.get("data-slug") for attrs in serial_page.select(".maatlog-post-card")]
        parallel_slugs = [attrs.get("data-slug") for attrs in parallel_page.select(".maatlog-post-card")]
        assert parallel_slugs == serial_slugs
        assert serial_slugs  # published posts must appear


MAATTOP_PARALLEL_FILES: dict[str, str | bytes] = {
    **PARALLEL_FILES,
    "hero-post.rst": """:maatlog-post: true
:maatlog-slug: hero-parallel
:maatlog-published-at: 2026-07-20T00:00:00Z

Hero Parallel
=============

.. maatlog:maattop:: images/hero.png
   :alt: Hero for the parallel build

Body.
""",
    "images/hero.png": b"png",
}


def test_parallel_write_copies_maattop_image(make_project: ProjectFactory) -> None:
    """maattop_node is stripped before post_process_images, so the master writer
    must promote the hero image itself or ``-j`` leaves a dangling ``_images`` src."""
    result = make_project(files=MAATTOP_PARALLEL_FILES, config=PARALLEL_CONFIG).build(parallel=4)

    page = result.html("hero-post.html")
    src = next(attrs["src"] for attrs in page.select(".maatlog-post-top-image-img"))
    assert src.startswith("_images/")
    assert result.path(src).is_file()


def test_parallel_maattop_image_matches_serial(make_project: ProjectFactory) -> None:
    """Separate projects: a shared outdir would keep the serial copy and hide the gap."""
    serial = make_project(files=MAATTOP_PARALLEL_FILES, config=PARALLEL_CONFIG).build(parallel=1)
    parallel = make_project(files=MAATTOP_PARALLEL_FILES, config=PARALLEL_CONFIG).build(parallel=4)

    serial_images = sorted(path.name for path in serial.path("_images").iterdir())
    parallel_images = sorted(path.name for path in parallel.path("_images").iterdir())
    assert parallel_images == serial_images
    assert "hero.png" in serial_images


def test_profile_pages_are_stable_under_parallel_builds(make_project: ProjectFactory) -> None:
    files = {
        "index.rst": "Root\n====\n\n.. toctree::\n\n   one\n",
        "one.md": (
            "---\nmaatlog-post: true\nmaatlog-slug: one\n"
            "maatlog-published-at: 2026-07-31T09:00:00Z\nmaatlog-authors: [alice]\n---\n# One\n\nBody.\n"
        ),
        "authors/alice.md": "# About Alice\n\nAbout body.\n",
        "authors/alice.png": PNG_1X1,
    }
    config = {
        "maatlog_authors": {"alice": "Alice Anderson"},
        "maatlog_author_profiles": {"alice": {"about_docname": "authors/alice", "avatar": "authors/alice.png"}},
    }

    serial = make_project(files=files, config=config).build().html("blog/author/alice.html").text
    parallel_site = make_project(files=files, config=config)
    parallel_result = parallel_site.build(parallel=2)

    assert parallel_result.html("blog/author/alice.html").text == serial
    assert (parallel_result.path("_images") / "alice.png").is_file()


def test_author_avatars_are_written_under_parallel_builds(make_project: ProjectFactory) -> None:
    # avatar は master プロセスの register_representative_images が拾う。
    # 右ペインが増えても _images の内容は変わらないことを固定する。
    site = make_project(
        files={
            "about.rst": "About\n=====\n\nBody.\n",
            "authors/alice.png": PNG_1X1,
        },
        theme="maatlog-default",
        config={
            "maatlog_authors": {"alice": "Alice"},
            "maatlog_default_author": "alice",
            "maatlog_author_profiles": {"alice": {"avatar": "authors/alice.png"}},
        },
    )
    result = site.build(parallel=2)
    page = result.html("about.html")
    image = page.select_one(".maatlog-author-summary-avatar-image")

    assert image is not None
    assert result.asset("_images/alice.png").exists()

"""Stale MaatLog archive page cleanup via owned output manifests."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from conftest import ProjectFactory

from maatlog.errors import MaatlogBuildError
from maatlog.outputs import commit_generated_outputs, safe_owned_path

# Three published posts → with page_size=1, all-posts archive has page 3.
THREE_POSTS = {
    "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
---
# One

First.
""",
    "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
---
# Two

Second.
""",
    "three.md": """---
maatlog-post: true
maatlog-slug: three
maatlog-published-at: 2026-07-29T09:00:00Z
---
# Three

Third.
""",
}

FEED_STALE_POSTS = {
    "keep.md": """---
maatlog-post: true
maatlog-slug: keep
maatlog-published-at: 2026-07-20T09:00:00Z
maatlog-tags: [keep]
---
# Keep

Stays.
""",
    "gone.md": """---
maatlog-post: true
maatlog-slug: gone
maatlog-published-at: 2026-07-19T09:00:00Z
maatlog-tags: [stale-tag]
---
# Gone

Removed on rebuild.
""",
}


def test_stale_owned_page_is_removed_after_success(make_project: ProjectFactory) -> None:
    """Shrinking page_size removes previously owned pagination HTML only."""
    project = make_project(files=THREE_POSTS, config={"maatlog_page_size": 1})
    project.build()
    stale = project.outdir / "blog/page/3.html"
    assert stale.exists()
    page_two = project.outdir / "blog/page/2.html"
    assert page_two.exists()

    project.config["maatlog_page_size"] = 10
    project.rewrite_conf()
    project.build(reuse_environment=True)

    assert not stale.exists()
    assert not page_two.exists()
    assert (project.outdir / "blog.html").exists()


def test_unowned_file_is_never_removed(make_project: ProjectFactory) -> None:
    """Files not recorded in the page manifest survive cleanup."""
    project = make_project(files=THREE_POSTS, config={"maatlog_page_size": 1})
    project.build()
    keep = project.outdir / "keep.html"
    keep.write_text("user", encoding="utf-8")

    project.config["maatlog_page_size"] = 10
    project.rewrite_conf()
    project.build(reuse_environment=True)

    assert keep.read_text(encoding="utf-8") == "user"
    assert not (project.outdir / "blog/page/3.html").exists()


def test_safe_owned_path_rejects_absolute_and_parent(tmp_path: Path) -> None:
    with pytest.raises(MaatlogBuildError) as absolute_exc:
        safe_owned_path(tmp_path, PurePosixPath("/etc/passwd"))
    assert absolute_exc.value.diagnostics[0].code == "maatlog.archive.output-unsafe"

    with pytest.raises(MaatlogBuildError) as parent_exc:
        safe_owned_path(tmp_path, PurePosixPath("../escape.html"))
    assert parent_exc.value.diagnostics[0].code == "maatlog.archive.output-unsafe"

    with pytest.raises(MaatlogBuildError) as nested_exc:
        safe_owned_path(tmp_path, PurePosixPath("blog/../../escape.html"))
    assert nested_exc.value.diagnostics[0].code == "maatlog.archive.output-unsafe"


def test_safe_owned_path_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.html"
    real.write_text("owned", encoding="utf-8")
    link = tmp_path / "link.html"
    link.symlink_to(real)

    with pytest.raises(MaatlogBuildError) as exc:
        safe_owned_path(tmp_path, PurePosixPath("link.html"))
    assert exc.value.diagnostics[0].code == "maatlog.archive.output-unsafe"


@pytest.mark.parametrize("points_outside", [False, True])
def test_commit_rejects_intermediate_directory_symlink(
    tmp_path: Path,
    points_outside: bool,
) -> None:
    outdir = tmp_path / "out"
    outdir.mkdir()
    target_dir = tmp_path / "outside" if points_outside else outdir / "real"
    target_dir.mkdir()
    victim = target_dir / "stale.html"
    victim.write_text("user-owned", encoding="utf-8")
    (outdir / "blog").symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(MaatlogBuildError) as error:
        commit_generated_outputs(outdir, {"blog/stale.html"}, set())

    assert error.value.diagnostics[0].code == "maatlog.archive.output-unsafe"
    assert victim.read_text(encoding="utf-8") == "user-owned"


def test_commit_does_not_remove_unowned_or_outside(tmp_path: Path) -> None:
    owned = tmp_path / "blog" / "page" / "3.html"
    owned.parent.mkdir(parents=True)
    owned.write_text("stale", encoding="utf-8")
    keep = tmp_path / "keep.html"
    keep.write_text("user", encoding="utf-8")
    outside = tmp_path.parent / "outside-maatlog-keep.html"
    outside.write_text("outside", encoding="utf-8")

    commit_generated_outputs(
        tmp_path,
        previous={"blog/page/3.html"},
        current=set(),
    )

    assert not owned.exists()
    assert keep.read_text(encoding="utf-8") == "user"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_stale_owned_feed_is_removed_after_success(make_project: ProjectFactory) -> None:
    """Removing the only post for a tag drops that taxonomy feed, not pages."""
    project = make_project(
        files=FEED_STALE_POSTS,
        config={"html_baseurl": "https://example.com/"},
    )
    project.build()
    stale_feed = project.outdir / "blog/tag/stale-tag/atom.xml"
    keep_feed = project.outdir / "blog/tag/keep/atom.xml"
    global_feed = project.outdir / "blog/atom.xml"
    assert stale_feed.is_file()
    assert keep_feed.is_file()
    assert global_feed.is_file()

    project.remove("gone.md")
    project.build(reuse_environment=True)

    assert not stale_feed.exists()
    assert keep_feed.is_file()
    assert global_feed.is_file()
    # Archive HTML for the stale tag should also go via page cleanup.
    assert not (project.outdir / "blog/tag/stale-tag.html").exists()


def test_disabling_feeds_removes_previous_owned_feeds(make_project: ProjectFactory) -> None:
    project = make_project(
        files=FEED_STALE_POSTS,
        config={"html_baseurl": "https://example.com/"},
    )
    project.build()
    assert (project.outdir / "blog/atom.xml").is_file()
    keep_page = project.outdir / "blog.html"
    assert keep_page.is_file()

    project.config["maatlog_generate_feeds"] = False
    project.rewrite_conf()
    project.build(reuse_environment=True)

    assert list(project.outdir.rglob("atom.xml")) == []
    assert keep_page.is_file()


def test_feed_cleanup_never_removes_page_outputs(make_project: ProjectFactory) -> None:
    project = make_project(
        files=FEED_STALE_POSTS,
        config={"html_baseurl": "https://example.com/"},
    )
    project.build()
    archive = project.outdir / "blog.html"
    tag_page = project.outdir / "blog/tag/keep.html"
    assert archive.is_file()
    assert tag_page.is_file()

    project.config["maatlog_generate_feeds"] = False
    project.rewrite_conf()
    project.build(reuse_environment=True)

    assert archive.is_file()
    assert tag_page.is_file()
    assert list(project.outdir.rglob("atom.xml")) == []

"""Integration tests for MaatLog archive HTML pages (html / dirhtml)."""

from __future__ import annotations

import pytest
from conftest import ProjectFactory

from maatlog.errors import MaatlogBuildError

# SOURCE_DATE_EPOCH default in fixtures is 2026-08-01T00:00:00Z — publish before that.
MULTIPAGE_PROJECT = {
    "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
---
# One

First sphinx post.
""",
    "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
---
# Two

Second sphinx post.
""",
    "three.md": """---
maatlog-post: true
maatlog-slug: three
maatlog-published-at: 2026-07-29T09:00:00Z
maatlog-tags: [python]
maatlog-authors: [bob]
---
# Three

Non-sphinx post for pagination contrast.
""",
}


@pytest.mark.parametrize(
    (
        "builder",
        "archive_path",
        "page_two_path",
        "next_href",
        "prev_href",
        "card_href_page1",
        "card_href_page2",
    ),
    [
        (
            "html",
            "blog/tag/sphinx.html",
            "blog/tag/sphinx/page/2.html",
            "sphinx/page/2.html",
            "../../sphinx.html",
            "../../one.html",
            "../../../../two.html",
        ),
        (
            "dirhtml",
            "blog/tag/sphinx/index.html",
            "blog/tag/sphinx/page/2/index.html",
            "page/2/",
            "../../",
            "../../../one/",
            "../../../../../two/",
        ),
    ],
)
def test_archive_uses_builder_uri(
    make_project: ProjectFactory,
    builder: str,
    archive_path: str,
    page_two_path: str,
    next_href: str,
    prev_href: str,
    card_href_page1: str,
    card_href_page2: str,
) -> None:
    """Tag archive paths and relative hrefs follow html vs dirhtml Builder URI rules."""
    result = make_project(
        files=MULTIPAGE_PROJECT,
        builder=builder,
        config={"maatlog_page_size": 1},
    ).build()
    assert result.path(archive_path).exists()
    assert result.path(page_two_path).exists()

    page1 = result.html(archive_path)
    assert page1.select_one(".maatlog-pagination")
    next_link = page1.select_one(".maatlog-pagination-next")
    assert next_link is not None
    assert next_link["href"] == next_href
    page_link = page1.select_one(".maatlog-pagination-page")
    assert page_link is not None
    assert page_link["href"] == next_href
    assert page1.select_one(".maatlog-pagination-prev") is None
    # Post card link (internal title <a> has no class — match by href attribute).
    assert page1.select_one(f"[href='{card_href_page1}']") is not None
    assert page1.select_one(".maatlog-post-card") is not None

    page2 = result.html(page_two_path)
    prev_link = page2.select_one(".maatlog-pagination-prev")
    assert prev_link is not None
    assert prev_link["href"] == prev_href
    assert page2.select_one(".maatlog-pagination-next") is None
    assert page2.select_one(f"[href='{card_href_page2}']") is not None


@pytest.mark.parametrize(
    (
        "builder",
        "all_posts_path",
        "page_two_path",
        "next_href",
        "prev_href",
        "page_two_link_href",
        "card_hrefs_page1",
        "card_href_page2",
    ),
    [
        (
            "html",
            "blog.html",
            "blog/page/2.html",
            "blog/page/2.html",
            "../../blog.html",
            "blog/page/2.html",
            ("one.html", "two.html"),
            "../../three.html",
        ),
        (
            "dirhtml",
            "blog/index.html",
            "blog/page/2/index.html",
            "page/2/",
            "../../",
            "page/2/",
            ("../one/", "../two/"),
            "../../../three/",
        ),
    ],
)
def test_all_posts_archive_paginates(
    make_project: ProjectFactory,
    builder: str,
    all_posts_path: str,
    page_two_path: str,
    next_href: str,
    prev_href: str,
    page_two_link_href: str,
    card_hrefs_page1: tuple[str, ...],
    card_href_page2: str,
) -> None:
    result = make_project(
        files=MULTIPAGE_PROJECT,
        builder=builder,
        config={"maatlog_page_size": 2},
    ).build()
    assert result.path(all_posts_path).exists()
    assert result.path(page_two_path).exists()

    page = result.html(all_posts_path)
    assert page.select_one(".maatlog-archive[data-maatlog-component='archive']")
    assert page.select_one(".maatlog-pagination")
    assert page.select_one(".maatlog-post-card")

    next_link = page.select_one(".maatlog-pagination-next")
    assert next_link is not None
    assert next_link["href"] == next_href
    page_link = page.select_one(".maatlog-pagination-page")
    assert page_link is not None
    assert page_link["href"] == page_two_link_href
    assert page.select_one(".maatlog-pagination-prev") is None
    for href in card_hrefs_page1:
        assert page.select_one(f"[href='{href}']") is not None

    page2 = result.html(page_two_path)
    prev_link = page2.select_one(".maatlog-pagination-prev")
    assert prev_link is not None
    assert prev_link["href"] == prev_href
    assert page2.select_one(".maatlog-pagination-next") is None
    assert page2.select_one(f"[href='{card_href_page2}']") is not None


def test_empty_all_posts_archive_is_generated(make_project: ProjectFactory) -> None:
    result = make_project(files={"notes.rst": "Notes\n=====\n\nNo posts here.\n"}).build()
    assert result.path("blog.html").exists()
    page = result.html("blog.html")
    assert page.select_one(".maatlog-archive")
    assert "No posts." in page.text
    assert page.select_one(".maatlog-pagination")


def test_archive_root_collision_with_source_doc_fails(make_project: ProjectFactory) -> None:
    """Projected archive root ``blog`` must not collide with source ``blog.rst``."""
    project = make_project(
        files={
            "blog.rst": "Blog\n====\n\nUser-owned blog page.\n",
            "post.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
---
# One

Body.
""",
        },
    )

    with pytest.raises(MaatlogBuildError) as error:
        project.build()

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.generated-docname.conflict"
    assert diagnostic.field == "docname"
    assert diagnostic.value == "blog"
    assert diagnostic.expected == "unused relative docname"


def test_source_page_survives_generated_docname_conflict(make_project: ProjectFactory) -> None:
    """Conflict must fail before archive write/cleanup overwrites user HTML."""
    project = make_project(
        files={
            "blog.rst": "Blog\n====\n\nUser-owned blog page.\n",
            "post.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
---
# One

Body.
""",
        },
        config={"maatlog_archive_docname": "archives"},
    )
    project.build()
    blog_html = project.outdir / "blog.html"
    assert blog_html.is_file()
    assert "User-owned blog page" in blog_html.read_text(encoding="utf-8")

    project.config["maatlog_archive_docname"] = "blog"
    project.rewrite_conf()
    with pytest.raises(MaatlogBuildError) as error:
        project.build(reuse_environment=True)

    assert error.value.diagnostics[0].code == "maatlog.generated-docname.conflict"
    assert blog_html.is_file()
    assert "User-owned blog page" in blog_html.read_text(encoding="utf-8")

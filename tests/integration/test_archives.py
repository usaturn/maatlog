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
    assert "No posts yet." in page.text
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


def test_post_card_date_is_time_element(make_project: ProjectFactory) -> None:
    """Card dates expose machine-readable ISO 8601 and a locale-free display form."""
    result = make_project(files=MULTIPAGE_PROJECT).build()
    page = result.html("blog.html")

    date = page.select_one("time.maatlog-post-card-date")
    assert date is not None
    assert date["datetime"].startswith("2026-07-31T09:00:00")
    assert "2026-07-31" in page


# 4 posts so the home page has 3 featured + 1 older. Publish before SOURCE_DATE_EPOCH.
FOUR_POST_PROJECT = {
    f"post{n}.md": f"""---
maatlog-post: true
maatlog-slug: post{n}
maatlog-published-at: 2026-07-2{n}T09:00:00Z
maatlog-tags: [sphinx]
---
# Post {n}

Body of post {n}.
"""
    for n in (1, 2, 3, 4)
}


def test_home_features_three_posts(make_project: ProjectFactory) -> None:
    """The archive root page 1 promotes the newest three posts."""
    result = make_project(files=FOUR_POST_PROJECT).build()
    page = result.html("blog.html")

    featured = page.select(".maatlog-post-featured .maatlog-post-card")
    assert len(featured) == 3
    assert all("maatlog-post-card-featured" in card["class"] for card in featured)
    assert "Older posts" in page
    # The 4th post is outside the featured grid.
    assert len(page.select(".maatlog-post-list .maatlog-post-card")) == 4


def test_home_with_three_posts_has_no_older_heading(make_project: ProjectFactory) -> None:
    """With three or fewer posts there is nothing left to put under 'Older posts'."""
    files = {name: body for name, body in FOUR_POST_PROJECT.items() if name != "post1.md"}
    result = make_project(files=files).build()
    page = result.html("blog.html")

    assert len(page.select(".maatlog-post-featured .maatlog-post-card")) == 3
    assert "Older posts" not in page


def test_taxonomy_archive_has_no_featured_grid(make_project: ProjectFactory) -> None:
    """Featured promotion belongs to the home page only."""
    result = make_project(files=FOUR_POST_PROJECT).build()
    page = result.html("blog/tag/sphinx.html")

    assert page.select_one(".maatlog-post-featured") is None
    assert page.select_one(".maatlog-post-card") is not None


def test_home_page_two_has_no_featured_grid(make_project: ProjectFactory) -> None:
    """Only page 1 of the archive root is the home page."""
    result = make_project(files=FOUR_POST_PROJECT, config={"maatlog_page_size": 2}).build()
    page = result.html("blog/page/2.html")

    assert page.select_one(".maatlog-post-featured") is None
    assert page.select_one(".maatlog-hero") is None
    assert page.select_one(".maatlog-post-card") is not None


def test_pagination_offers_an_older_posts_link(make_project: ProjectFactory) -> None:
    """Numbered pagination is joined by an explicit 'keep reading' affordance."""
    result = make_project(files=FOUR_POST_PROJECT, config={"maatlog_page_size": 2}).build()
    page1 = result.html("blog.html")

    more = page1.select_one("a.maatlog-pagination-more")
    next_link = page1.select_one(".maatlog-pagination-next")
    assert more is not None
    assert next_link is not None
    assert more["href"] == next_link["href"]
    assert "Older posts" in page1

    last = result.html("blog/page/2.html")
    assert last.select_one("a.maatlog-pagination-more") is None


def test_archive_root_first_page_is_home_and_has_site(make_project: ProjectFactory) -> None:
    """Without maatlog_home_docname, the archive root page 1 is the blog home."""
    result = make_project(
        files=MULTIPAGE_PROJECT,
        config={"maatlog_page_size": 2, "project": "Example Blog", "maatlog_tagline": "Notes"},
    ).build()

    page = result.html("blog.html")
    assert page.select_one(".maatlog-hero") is not None
    assert "Example Blog" in page
    assert "Notes" in page
    page2 = result.html("blog/page/2.html")
    assert page2.select_one(".maatlog-hero") is None


def test_archive_cards_expose_taxonomy_links(make_project: ProjectFactory) -> None:
    result = make_project(files=MULTIPAGE_PROJECT, config={"maatlog_page_size": 10}).build()
    page = result.html("blog.html")
    assert page.select_one(".maatlog-post-card [href='blog/tag/sphinx.html']") is not None
    assert page.select_one(".maatlog-post-card [href='blog/category/engineering.html']") is not None
    assert page.select_one(".maatlog-post-card [href='blog/author/alice.html']") is not None


def test_home_renders_hero(make_project: ProjectFactory) -> None:
    """The archive root page 1 leads with site identity, scale and feed links."""
    result = make_project(
        files=FOUR_POST_PROJECT,
        config={
            "project": "Example Blog",
            "maatlog_tagline": "Notes on Sphinx",
        },
    ).build()
    page = result.html("blog.html")

    hero = page.select_one(".maatlog-hero[data-maatlog-component='hero']")
    assert hero is not None
    # The hero replaces the plain archive header; the required class stays.
    assert "maatlog-archive-header" in hero["class"]
    assert "Example Blog" in page
    assert "Notes on Sphinx" in page
    assert "4 posts" in page

    updated = page.select_one("time.maatlog-hero-updated")
    assert updated is not None
    assert updated["datetime"].startswith("2026-07-24T09:00:00")
    assert page.select_one(".maatlog-hero .maatlog-feed-link") is not None


def test_hero_omits_tagline_when_unset(make_project: ProjectFactory) -> None:
    """No tagline configured means no empty paragraph in the markup."""
    result = make_project(files=FOUR_POST_PROJECT).build()
    page = result.html("blog.html")

    assert page.select_one(".maatlog-hero") is not None
    assert page.select_one(".maatlog-hero-tagline") is None


def test_taxonomy_archive_keeps_plain_header(make_project: ProjectFactory) -> None:
    """Only the home page gets the hero; other archives keep label + count."""
    result = make_project(files=FOUR_POST_PROJECT).build()
    page = result.html("blog/tag/sphinx.html")

    assert page.select_one(".maatlog-hero") is None
    assert page.select_one(".maatlog-archive-header") is not None
    assert page.select_one(".maatlog-archive-count") is not None


def test_empty_home_keeps_hero_and_explains(make_project: ProjectFactory) -> None:
    """A blog with no posts still renders as a site, and says what to do next."""
    files = {"about.md": "# About\n\nNo posts here yet.\n"}
    result = make_project(files=files).build()
    page = result.html("blog.html")

    assert page.select_one(".maatlog-hero") is not None
    assert "0 posts" in page
    assert page.select_one(".maatlog-archive-empty") is not None
    assert "No posts yet." in page
    assert "maatlog metadata" in page
    assert page.select_one(".maatlog-post-featured") is None
    assert "Older posts" not in page


# 7 tags across 2 calendar years: exercises top-5 truncation and year grouping.
MANY_TAXONOMY_PROJECT = {
    "a.md": """---
maatlog-post: true
maatlog-slug: a
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [t1, t2, t3, t4, t5, t6, t7]
---
# A

Post A.
""",
    "b.md": """---
maatlog-post: true
maatlog-slug: b
maatlog-published-at: 2025-12-31T09:00:00Z
maatlog-tags: [t1]
---
# B

Post B.
""",
}


def test_sidebar_truncates_tags_to_top_five(make_project: ProjectFactory) -> None:
    """Long tag lists stay a fixed height; the rest goes behind a disclosure."""
    result = make_project(files=MANY_TAXONOMY_PROJECT).build()
    page = result.html("blog.html")

    # The helper's selector parser supports descendant combinators only, so count
    # all tag links and the disclosed subset separately (7 total, 5 shown, 2 hidden).
    assert len(page.select(".maatlog-taxonomy-tags a")) == 7
    assert len(page.select("details.maatlog-taxonomy-more a")) == 2
    assert page.select_one("details.maatlog-taxonomy-more") is not None
    assert "All tags (7)" in page


def test_sidebar_groups_months_by_year(make_project: ProjectFactory) -> None:
    """Month archives nest under their calendar year."""
    result = make_project(files=MANY_TAXONOMY_PROJECT).build()
    page = result.html("blog.html")

    years = page.select("details.maatlog-taxonomy-year")
    assert len(years) == 2
    assert "2026" in page
    assert "2025" in page


def test_post_taxonomy_links_include_screen_reader_separators(make_project: ProjectFactory) -> None:
    result = make_project(files=MANY_TAXONOMY_PROJECT).build()

    # カードも記事ページと同じく、区切りは読み上げ専用にする。pill の外へ
    # カンマが落ちると二重の区切りになる。
    card_page = result.html("blog.html").text
    assert '>t1</a><span class="maatlog-visually-hidden">, </span>' in card_page
    assert ">t1</a>, <a" not in card_page
    page = result.html("a.html")
    assert page.select_one(".maatlog-post-tags .maatlog-tag-link[href='blog/tag/t1.html']")
    assert page.select_one(".maatlog-post-tags .maatlog-tag-link[href='blog/tag/t2.html']")
    separators = page.select(".maatlog-post-tags .maatlog-visually-hidden")
    assert len(separators) == 6
    assert page.text.count('<span class="maatlog-visually-hidden">, </span>') == 6


def test_scheduled_post_does_not_link_to_missing_taxonomy_archive(
    make_project: ProjectFactory,
) -> None:
    files = {
        "published.md": """---
maatlog-post: true
maatlog-slug: published
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [shared]
---
# Published
""",
        "scheduled.md": """---
maatlog-post: true
maatlog-slug: scheduled
maatlog-published-at: 2027-07-31T09:00:00Z
maatlog-tags: [shared, secret]
---
# Scheduled
""",
    }
    result = make_project(files=files).build()
    page = result.html("scheduled.html")

    assert page.select_one(".maatlog-post-tags [href='blog/tag/shared.html']") is not None
    assert page.select_one(".maatlog-post-tags [href='blog/tag/secret.html']") is None
    assert page.select_one(".maatlog-post-tags span.maatlog-taxonomy-link") is not None
    assert not result.path("blog/tag/secret.html").exists()


def test_scheduled_post_gains_taxonomy_link_after_publish_without_feeds(
    make_project: ProjectFactory,
) -> None:
    files = {
        "scheduled.md": """---
maatlog-post: true
maatlog-slug: future-post
maatlog-published-at: 2026-08-01T12:00:00Z
maatlog-tags: [secret]
---
# Future Post

Scheduled body.
""",
    }
    project = make_project(
        files=files,
        source_date_epoch="1782864000",
        config={"maatlog_generate_feeds": False, "maatlog_timezone": "UTC"},
    )
    first = project.build(reuse_environment=False)
    first_page = first.html("scheduled.html")
    assert first_page.select_one(".maatlog-post-tags [href='blog/tag/secret.html']") is None
    assert first_page.select_one(".maatlog-post-tags span.maatlog-taxonomy-link") is not None
    assert not first.path("blog/tag/secret.html").exists()

    project.source_date_epoch = "1786752000"
    second = project.build(reuse_environment=True)
    second_page = second.html("scheduled.html")
    assert second_page.select_one(".maatlog-post-tags [href='blog/tag/secret.html']") is not None
    assert second.path("blog/tag/secret.html").exists()


def test_non_featured_cards_are_wrapped_in_a_grid(make_project: ProjectFactory) -> None:
    # featured の下に並ぶカードだけをグリッドに載せるため、専用のラッパが要る。
    # .maatlog-post-list 直下のままだと hero / featured / 見出しまでグリッドの子になる。
    result = make_project(files=FOUR_POST_PROJECT).build()
    page = result.html("blog.html")

    grid = page.select_one(".maatlog-post-list .maatlog-post-grid")
    assert grid is not None
    assert page.select_one(".maatlog-post-grid .maatlog-post-card") is not None
    assert page.select_one(".maatlog-post-grid .maatlog-post-card-featured") is None
    assert page.select_one(".maatlog-post-grid .maatlog-post-list-heading") is None


def test_taxonomy_archive_cards_also_ride_the_grid(make_project: ProjectFactory) -> None:
    # featured を出さない一覧でも、カードは同じグリッドで並ぶ。
    result = make_project(files=FOUR_POST_PROJECT).build()
    page = result.html("blog/tag/sphinx.html")

    assert page.select_one(".maatlog-post-featured") is None
    assert page.select_one(".maatlog-post-grid .maatlog-post-card") is not None

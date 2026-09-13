"""Integration tests for the blog top and archive social metadata (issue #211)."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import HtmlPage, ProjectFactory
from social_metadata import (
    assert_no_duplicate_social_metadata,
    json_ld_objects,
    open_graph_values,
    twitter_values,
)

SITE_FILES: dict[str, str | bytes] = {
    "index.rst": "Welcome\n=======\n\nBlog home.\n",
    "one.rst": (
        ":maatlog-post: true\n:maatlog-slug: one\n:maatlog-published-at: 2026-08-01T00:00:00Z\n"
        ":maatlog-tags: sphinx\n:maatlog-categories: engineering\n:maatlog-authors: alice\n\nOne\n===\n"
    ),
    "two.rst": (
        ":maatlog-post: true\n:maatlog-slug: two\n:maatlog-published-at: 2026-08-02T00:00:00Z\n"
        ":maatlog-tags: sphinx\n:maatlog-categories: engineering\n:maatlog-authors: alice\n\nTwo\n===\n"
    ),
    "three.rst": (
        ":maatlog-post: true\n:maatlog-slug: three\n:maatlog-published-at: 2026-08-03T00:00:00Z\n"
        ":maatlog-tags: sphinx\n:maatlog-categories: engineering\n:maatlog-authors: alice\n\nThree\n=====\n"
    ),
}

SITE_CONFIG: dict[str, object] = {
    "html_baseurl": "https://example.test/",
    "project": "Example Blog",
    "maatlog_tagline": "Notes on Sphinx",
    # Display names only. No maatlog_author_profiles, so blog/author/alice.html is an
    # archive (#211), not a profile (#210).
    "maatlog_authors": {"alice": "Alice"},
}

HOME_CONFIG: dict[str, object] = {**SITE_CONFIG, "maatlog_home_docname": "index"}


def _website_objects(page: HtmlPage) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for payload in json_ld_objects(page):
        if not isinstance(payload, dict):
            continue
        obj = cast("dict[str, object]", payload)
        if obj.get("@type") == "WebSite":
            found.append(obj)
    return found


def _blog_top_relative(builder: str, *, configured_home: bool) -> str:
    # The root document lands on index.html under both builders; the archive root is
    # blog.html under html and blog/index.html under dirhtml.
    if configured_home:
        return "index.html"
    return "blog.html" if builder == "html" else "blog/index.html"


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("configured_home", [True, False])
def test_blog_top_carries_website_json_ld(make_project: ProjectFactory, builder: str, configured_home: bool) -> None:
    result = make_project(
        files=SITE_FILES,
        config=HOME_CONFIG if configured_home else SITE_CONFIG,
        builder=builder,
        source_date_epoch="1789171200",
    ).build()

    page = result.html(_blog_top_relative(builder, configured_home=configured_home))
    if configured_home:
        expected_url = "https://example.test/index.html" if builder == "html" else "https://example.test/"
    else:
        expected_url = "https://example.test/blog.html" if builder == "html" else "https://example.test/blog/"
    assert open_graph_values(page, "og:type") == ["website"]
    assert open_graph_values(page, "og:title") == ["Example Blog"]
    assert open_graph_values(page, "og:description") == ["Notes on Sphinx"]
    assert open_graph_values(page, "og:site_name") == []
    assert open_graph_values(page, "og:url") == [expected_url]
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert twitter_values(page, "twitter:title") == ["Example Blog"]

    websites = _website_objects(page)
    assert len(websites) == 1
    assert websites[0]["name"] == "Example Blog"
    assert websites[0]["description"] == "Notes on Sphinx"
    assert websites[0]["url"] == expected_url


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("configured_home", [True, False])
def test_exactly_one_page_in_the_site_carries_website(
    make_project: ProjectFactory, builder: str, configured_home: bool
) -> None:
    result = make_project(
        files=SITE_FILES,
        config=HOME_CONFIG if configured_home else SITE_CONFIG,
        builder=builder,
        source_date_epoch="1789171200",
    ).build()

    carriers = [
        path.relative_to(result.path("")).as_posix()
        for path in sorted(result.path("").rglob("*.html"))
        if _website_objects(HtmlPage(path.read_text(encoding="utf-8")))
    ]
    if configured_home:
        assert carriers == ["index.html"]
    else:
        assert carriers == ["blog.html" if builder == "html" else "blog/index.html"]


def test_taxonomy_archives_carry_social_metadata_without_json_ld(make_project: ProjectFactory) -> None:
    result = make_project(files=SITE_FILES, config=HOME_CONFIG, source_date_epoch="1789171200").build()

    # blog/author/alice.html is page 1 without maatlog_author_profiles, so it is an
    # archive for this lane, not a profile.
    for relative in (
        "blog.html",
        "blog/tag/sphinx.html",
        "blog/category/engineering.html",
        "blog/author/alice.html",
        "blog/month/2026-08.html",
    ):
        page = result.html(relative)
        assert open_graph_values(page, "og:type") == ["website"], relative
        assert open_graph_values(page, "og:site_name") == ["Example Blog"], relative
        assert open_graph_values(page, "og:title") != [], relative
        assert open_graph_values(page, "og:description") == [], relative
        assert twitter_values(page, "twitter:card") == ["summary"], relative
        assert json_ld_objects(page) == [], relative


def test_configured_author_profile_page_two_is_an_archive(make_project: ProjectFactory) -> None:
    # page 1 with maatlog_author_profiles is page_kind="profile" (#210). page 2 stays archive.
    result = make_project(
        files=SITE_FILES,
        config={
            **HOME_CONFIG,
            "maatlog_author_profiles": {"alice": {"role": "Editor"}},
            "maatlog_page_size": 1,
        },
        source_date_epoch="1789171200",
    ).build()

    page_one = result.html("blog/author/alice.html")
    page_two = result.html("blog/author/alice/page/2.html")

    assert "website" not in open_graph_values(page_one, "og:type")
    assert _website_objects(page_one) == []

    assert open_graph_values(page_two, "og:type") == ["website"]
    assert open_graph_values(page_two, "og:site_name") == ["Example Blog"]
    assert open_graph_values(page_two, "og:title") != []
    assert open_graph_values(page_two, "og:description") == []
    assert twitter_values(page_two, "twitter:card") == ["summary"]
    assert json_ld_objects(page_two) == []


def test_pagination_pages_carry_social_metadata_without_website(make_project: ProjectFactory) -> None:
    result = make_project(
        files=SITE_FILES,
        config={**HOME_CONFIG, "maatlog_page_size": 1},
        source_date_epoch="1789171200",
    ).build()

    page = result.html("blog/page/2.html")
    assert open_graph_values(page, "og:type") == ["website"]
    assert open_graph_values(page, "og:site_name") == ["Example Blog"]
    assert json_ld_objects(page) == []


def test_empty_archive_still_carries_website(make_project: ProjectFactory) -> None:
    result = make_project(
        files={"index.rst": "Welcome\n=======\n\nNo posts yet.\n"},
        config=SITE_CONFIG,
        source_date_epoch="1789171200",
    ).build()

    page = result.html("blog.html")
    websites = _website_objects(page)
    assert len(websites) == 1
    assert websites[0]["name"] == "Example Blog"
    assert open_graph_values(page, "og:title") == ["Example Blog"]


def test_without_baseurl_website_keeps_name_and_drops_url(make_project: ProjectFactory) -> None:
    result = make_project(
        files=SITE_FILES,
        config={**HOME_CONFIG, "html_baseurl": "", "maatlog_generate_feeds": False},
        source_date_epoch="1789171200",
    ).build()

    page = result.html("index.html")
    assert open_graph_values(page, "og:url") == []
    website = _website_objects(page)[0]
    assert website["name"] == "Example Blog"
    assert "url" not in website


def test_without_project_name_falls_back_to_archive_label(make_project: ProjectFactory) -> None:
    result = make_project(
        files=SITE_FILES,
        config={**HOME_CONFIG, "project": "", "maatlog_tagline": None},
        source_date_epoch="1789171200",
    ).build()

    page = result.html("index.html")
    assert open_graph_values(page, "og:title") == ["Posts"]
    assert _website_objects(page) == []


def test_hostile_site_title_is_escaped_in_meta_and_json_ld(make_project: ProjectFactory) -> None:
    hostile = 'Blog </script><script>alert("x")</script> & <b> 日本語'
    result = make_project(
        files=SITE_FILES,
        config={**HOME_CONFIG, "project": hostile, "maatlog_tagline": hostile},
        source_date_epoch="1789171200",
    ).build()

    page = result.html("index.html")
    assert open_graph_values(page, "og:title") == [hostile]
    website = _website_objects(page)[0]
    assert website["name"] == hostile
    assert website["description"] == hostile
    assert len(json_ld_objects(page)) == 1


def test_incremental_rebuild_keeps_metadata_unique(make_project: ProjectFactory) -> None:
    project = make_project(files=SITE_FILES, config=HOME_CONFIG, source_date_epoch="1789171200")
    first = project.build().html("index.html")
    project.write("index.rst", "Welcome\n=======\n\nBlog home, revised.\n")
    page = project.build(reuse_environment=True).html("index.html")

    assert_no_duplicate_social_metadata(page)
    assert open_graph_values(page, "og:title") == open_graph_values(first, "og:title")
    assert len(_website_objects(page)) == 1


def test_parallel_build_keeps_one_website(make_project: ProjectFactory) -> None:
    result = make_project(files=SITE_FILES, config=HOME_CONFIG, source_date_epoch="1789171200").build(parallel=4)

    carriers = 0
    for path in result.path("").rglob("*.html"):
        page = HtmlPage(path.read_text(encoding="utf-8"))
        assert_no_duplicate_social_metadata(page)
        carriers += len(_website_objects(page))
    assert carriers == 1


@pytest.mark.parametrize("builder", ["text", "singlehtml"])
def test_non_full_html_builders_emit_no_metadata(make_project: ProjectFactory, builder: str) -> None:
    result = make_project(
        files=SITE_FILES,
        config={**HOME_CONFIG, "html_baseurl": ""},
        builder=builder,
        source_date_epoch="1789171200",
    ).build()

    output = result.path("index.txt" if builder == "text" else "index.html").read_text(encoding="utf-8")
    assert 'property="og:' not in output
    assert "application/ld+json" not in output


def test_canonical_and_feed_discovery_do_not_regress(make_project: ProjectFactory) -> None:
    result = make_project(files=SITE_FILES, config=HOME_CONFIG, source_date_epoch="1789171200").build()

    for relative in ("index.html", "blog.html", "blog/tag/sphinx.html"):
        page = result.html(relative)
        assert len(page.select('link[rel="canonical"]')) == 1, relative
        assert len(page.select('link[type="application/atom+xml"]')) >= 1, relative


CANONICAL_HOME_FILES: dict[str, str | bytes] = {
    **SITE_FILES,
    "index.rst": (
        ":maatlog-post: true\n:maatlog-slug: home\n:maatlog-published-at: 2026-08-04T00:00:00Z\n"
        ":maatlog-canonical-url: https://canonical.example/elsewhere\n\nWelcome\n=======\n\nBlog home.\n"
    ),
}


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_home_post_with_explicit_canonical_agrees_with_og_url(make_project: ProjectFactory, builder: str) -> None:
    """An explicit ``maatlog-canonical-url`` owns the crawler URL the blog top publishes.

    ``extension.py`` already routes that value into ``rel="canonical"``. ``og:url`` and
    ``WebSite.url`` name the same document, so all three have to agree: a crawler that
    reads two different URLs for one page cannot tell which identity is the real one.
    """
    result = make_project(
        files=CANONICAL_HOME_FILES,
        config=HOME_CONFIG,
        builder=builder,
        source_date_epoch="1789171200",
    ).build()

    page = result.html("index.html")
    canonical = page.select_one('link[rel="canonical"]')
    assert canonical is not None
    assert canonical["href"] == "https://canonical.example/elsewhere"
    assert open_graph_values(page, "og:url") == ["https://canonical.example/elsewhere"]

    websites = _website_objects(page)
    assert len(websites) == 1
    assert websites[0]["url"] == "https://canonical.example/elsewhere"

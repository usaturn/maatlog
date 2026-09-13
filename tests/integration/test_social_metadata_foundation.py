from __future__ import annotations

import pytest
from conftest import HtmlPage, ProjectFactory
from jinja2 import Environment
from social_metadata import assert_no_crawler_urls, assert_no_duplicate_social_metadata, assert_no_social_metadata

import maatlog.extension as extension
from maatlog.social_metadata import SocialMetadataView
from maatlog.theme_api import collect_template_block_names
from maatlog.views import MaatlogTemplateContext, PageKind

FOUNDATION_FILES: dict[str, str | bytes] = {
    "index.rst": "Home\n====\n",
    "post.rst": (
        ":maatlog-post: true\n:maatlog-slug: post\n:maatlog-published-at: 2026-09-01T00:00:00Z\n"
        ":maatlog-tags: sphinx\n:maatlog-categories: engineering\n:maatlog-authors: alice\n\nPost\n====\n"
    ),
    "normal.rst": "Normal\n======\n",
    "authors/alice.md": "# Alice\n",
}

FOUNDATION_CONFIG = {
    "html_baseurl": "https://example.test/docs/",
    "maatlog_home_docname": "index",
    "maatlog_authors": {"alice": "Alice"},
    "maatlog_author_profiles": {"alice": {"about_docname": "authors/alice"}},
}


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_full_html_projects_every_page_kind(
    make_project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    calls: list[tuple[PageKind, str | None]] = []

    def projector(context: MaatlogTemplateContext, *, page_url: str | None) -> SocialMetadataView:
        calls.append((context.page_kind, page_url))
        return SocialMetadataView()

    monkeypatch.setattr(extension, "project_social_metadata", projector)
    result = make_project(
        files=FOUNDATION_FILES,
        config=FOUNDATION_CONFIG,
        builder=builder,
        source_date_epoch="1789171200",
    ).build()
    assert result.path("index.html").is_file()
    assert {kind for kind, _ in calls} >= {"home", "post", "profile", "archive", "normal"}
    assert all(url is not None and url.startswith("https://example.test/docs/") for _, url in calls)
    suffix = ".html" if builder == "html" else "/"
    home_uri = "index.html" if builder == "html" else ""
    assert ("home", f"https://example.test/docs/{home_uri}") in calls
    for kind, docname in (("post", "post"), ("profile", "blog/author/alice"), ("normal", "normal")):
        assert (kind, f"https://example.test/docs/{docname}{suffix}") in calls
    assert ("archive", f"https://example.test/docs/blog{suffix}") in calls
    for path in result.path("").rglob("*.html"):
        assert_no_social_metadata(HtmlPage(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("builder", ["text", "singlehtml"])
def test_non_full_html_skips_metadata_without_baseurl(
    make_project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    def fail(context: MaatlogTemplateContext, *, page_url: str | None) -> SocialMetadataView:
        raise AssertionError("metadata projector must not run")

    monkeypatch.setattr(extension, "project_social_metadata", fail)
    result = make_project(
        files=FOUNDATION_FILES,
        config={**FOUNDATION_CONFIG, "html_baseurl": ""},
        builder=builder,
        source_date_epoch="1789171200",
    ).build()
    assert result.path("index.txt" if builder == "text" else "index.html").is_file()
    assert "html_baseurl" not in result.warnings


def test_rendered_head_preserves_discovery(make_project: ProjectFactory) -> None:
    result = make_project(
        files=FOUNDATION_FILES,
        config=FOUNDATION_CONFIG,
        source_date_epoch="1789171200",
    ).build()
    # index.html is the blog top and blog.html an archive (issue #211), the profile page
    # carries its own metadata (#210) and the post its own (#209), so no blog page here is
    # metadata-free any more. What this test pins is the discovery markup beside it.
    post = result.html("post.html")
    assert len(post.select('link[rel="canonical"]')) == 1
    assert len(post.select('link[type="application/atom+xml"]')) == 5
    assert len(post.select('meta[property="og:type"]')) == 1
    for relative, count in (("index.html", 1), ("blog.html", 1), ("blog/author/alice.html", 2)):
        page = result.html(relative)
        assert len(page.select('link[type="application/atom+xml"]')) == count
        assert len(page.select('link[rel="canonical"]')) == 1
    normal = result.html("normal.html")
    assert_no_social_metadata(normal)
    # Preserve Sphinx's canonical without adding a MaatLog canonical.
    assert normal.select('link[rel="canonical"]') == [
        {"rel": "canonical", "href": "https://example.test/docs/normal.html"}
    ]
    assert normal.select('link[type="application/atom+xml"]') == []


def test_social_metadata_block_is_inherited(make_project: ProjectFactory) -> None:
    result = make_project(
        files=FOUNDATION_FILES,
        config=FOUNDATION_CONFIG,
        source_date_epoch="1789171200",
    ).build()
    environment = result.app.builder.templates.environment
    assert isinstance(environment, Environment)
    assert "maatlog_social_metadata" in collect_template_block_names(environment, "maatlog/post.html")


def test_social_metadata_block_override_renders_in_head(make_project: ProjectFactory) -> None:
    result = make_project(
        files={
            **FOUNDATION_FILES,
            "_templates/maatlog/post.html": (
                '{% extends "!maatlog/post.html" %}'
                "{% block maatlog_social_metadata %}"
                '<meta name="task-6-override" content="connected" />'
                "{% endblock %}"
            ),
        },
        config={**FOUNDATION_CONFIG, "templates_path": ["_templates"]},
        source_date_epoch="1789171200",
    ).build()
    page = result.html("post.html")
    assert page.select('head meta[name="task-6-override"]') == [{"name": "task-6-override", "content": "connected"}]
    assert len(page.select('link[rel="canonical"]')) == 1
    assert len(page.select('link[type="application/atom+xml"]')) == 5


def test_maatlog_head_override_with_super_renders_base_head_once(make_project: ProjectFactory) -> None:
    """The supported 1.22 pattern: override ``maatlog_head`` itself and call ``super()``.

    From 1.22 ``maatlog-base/layout.html`` owns ``maatlog_head``. Wrapping ``extrahead``
    and nesting ``maatlog_head`` inside it renders the nested block twice (once for the
    child's own ``extrahead``, once for the parent's via ``super()``), duplicating the
    canonical and Atom links. Overriding ``maatlog_head`` directly must keep the base
    head output exactly once.
    """
    result = make_project(
        files={
            **FOUNDATION_FILES,
            "_templates/maatlog/post.html": (
                '{% extends "!maatlog/post.html" %}'
                "{% block maatlog_head %}{{ super() }}"
                '<meta name="child-head" content="once" />'
                "{% endblock %}"
            ),
        },
        config={**FOUNDATION_CONFIG, "templates_path": ["_templates"]},
        source_date_epoch="1789171200",
    ).build()
    page = result.html("post.html")
    assert page.select('head meta[name="child-head"]') == [{"name": "child-head", "content": "once"}]
    assert len(page.select('link[rel="canonical"]')) == 1
    assert len(page.select('link[type="application/atom+xml"]')) == 5
    assert len(page.select('meta[property="og:type"]')) == 1


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_no_baseurl_omits_canonical_and_discovery(make_project: ProjectFactory, builder: str) -> None:
    result = make_project(
        files=FOUNDATION_FILES,
        config={**FOUNDATION_CONFIG, "html_baseurl": "", "maatlog_generate_feeds": False},
        builder=builder,
        source_date_epoch="1789171200",
    ).build()
    for path in result.path("").rglob("*.html"):
        page = HtmlPage(path.read_text(encoding="utf-8"))
        # Without html_baseurl no projector may advertise a crawler URL, whichever
        # lanes have landed. Text-only properties are each lane's own tests to cover.
        assert_no_crawler_urls(page)
        assert page.select('link[rel="canonical"]') == []
        assert page.select('link[type="application/atom+xml"]') == []


def test_incremental_title_change_preserves_head(make_project: ProjectFactory) -> None:
    project = make_project(
        files=FOUNDATION_FILES,
        config=FOUNDATION_CONFIG,
        source_date_epoch="1789171200",
    )
    first = project.build().html("post.html")
    source = FOUNDATION_FILES["post.rst"]
    assert isinstance(source, str)
    project.write("post.rst", source.replace("Post\n====", "Updated Post\n============"))
    page = project.build(reuse_environment=True).html("post.html")
    assert "Updated Post" in page.text
    assert len(page.select('link[rel="canonical"]')) == 1
    assert len(page.select('link[type="application/atom+xml"]')) == 5
    for selector in ('link[rel="canonical"]', 'link[type="application/atom+xml"]'):
        assert page.select(selector) == first.select(selector)
    assert page.select('meta[property="og:title"]') == [{"property": "og:title", "content": "Updated Post"}]


def test_parallel_build_preserves_head(make_project: ProjectFactory) -> None:
    result = make_project(
        files=FOUNDATION_FILES,
        config=FOUNDATION_CONFIG,
        source_date_epoch="1789171200",
    ).build(parallel=4)
    for path in result.path("").rglob("*.html"):
        page = HtmlPage(path.read_text(encoding="utf-8"))
        assert_no_duplicate_social_metadata(page)
        assert len(page.select('link[rel="canonical"]')) <= 1
        feeds = page.select('link[type="application/atom+xml"]')
        assert len(feeds) == len({feed["href"] for feed in feeds})
    assert len(result.html("post.html").select('link[type="application/atom+xml"]')) == 5
    assert len(result.html("index.html").select('link[type="application/atom+xml"]')) == 1
    assert len(result.html("blog.html").select('link[type="application/atom+xml"]')) == 1
    assert len(result.html("blog/author/alice.html").select('link[type="application/atom+xml"]')) == 2

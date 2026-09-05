"""The right rail's author summary across every page kind."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import ProjectFactory

from maatlog.extension import inject_maatlog_page_context

RAIL_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: hello
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-authors: [bob, alice]
---
# Hello

## Section A

Body.
""",
    "about.rst": "About\n=====\n\nA plain page that is not a post.\n",
}

RAIL_CONFIG: dict[str, object] = {
    "maatlog_authors": {"alice": "Alice Anderson", "bob": "Bob Brown"},
    "maatlog_author_profiles": {
        "alice": {"bio_short": "Python developer.", "links": [{"type": "github", "url": "https://github.com/x"}]}
    },
    "maatlog_default_author": "alice",
    "maatlog_archive_docname": "blog",
}


def _context_for(make_project: ProjectFactory, pagename: str, **overrides: object) -> dict[str, Any]:
    config = {**RAIL_CONFIG, **overrides}
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=config).build()
    context: dict[str, Any] = {}
    inject_maatlog_page_context(result.app, pagename, "page.html", context, None)
    return context


def test_post_page_summarises_the_posts_own_authors_in_order(make_project: ProjectFactory) -> None:
    summaries = _context_for(make_project, "post")["maatlog"]["author_summaries"]

    assert [item["slug"] for item in summaries] == ["bob", "alice"]
    assert summaries[0]["display_name"] == "Bob Brown"


def test_normal_page_summarises_the_default_author(make_project: ProjectFactory) -> None:
    summaries = _context_for(make_project, "about")["maatlog"]["author_summaries"]

    assert [item["slug"] for item in summaries] == ["alice"]
    assert summaries[0]["bio_short"] == "Python developer."
    assert summaries[0]["profile_url"].endswith("blog/author/alice.html")


UNPUBLISHED_DEFAULT_AUTHOR_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page that is not a post.\n",
}

UNPUBLISHED_DEFAULT_AUTHOR_CONFIG: dict[str, object] = {
    "maatlog_authors": {"alice": "Alice Anderson"},
    "maatlog_author_profiles": {"alice": {"bio_short": "Python developer."}},
    "maatlog_default_author": "alice",
    "maatlog_archive_docname": "blog",
}


def test_unpublished_default_author_display_name(make_project: ProjectFactory) -> None:
    from conftest import HtmlPage

    config = UNPUBLISHED_DEFAULT_AUTHOR_CONFIG
    result = make_project(
        files=UNPUBLISHED_DEFAULT_AUTHOR_PROJECT,
        theme="maatlog-default",
        config=config,
    ).build()
    context: dict[str, Any] = {}
    inject_maatlog_page_context(result.app, "about", "page.html", context, None)
    summaries = context["maatlog"]["author_summaries"]

    assert [item["slug"] for item in summaries] == ["alice"]
    assert summaries[0]["display_name"] == "Alice Anderson"
    assert summaries[0]["initials"] == "AA"
    assert summaries[0]["bio_short"] == "Python developer."
    assert summaries[0]["profile_url"] == ""

    page = HtmlPage(result.html("about.html").text)
    assert page.select_one(".maatlog-author-summary-name") is not None
    assert 'class="maatlog-author-summary-name">Alice Anderson</p>' in page
    assert '<span class="maatlog-author-summary-avatar-initials" aria-hidden="true">AA</span>' in page
    assert "Python developer." in page
    assert page.select_one(".maatlog-author-summary-profile-link") is None


def test_no_summary_without_a_default_author(make_project: ProjectFactory) -> None:
    summaries = _context_for(make_project, "about", maatlog_default_author=None)["maatlog"]["author_summaries"]

    assert summaries == ()


def test_the_first_configured_author_is_never_chosen_implicitly(make_project: ProjectFactory) -> None:
    # maatlog_authors の先頭は alice だが、既定著者を設定しなければ誰も選ばれない。
    summaries = _context_for(make_project, "about", maatlog_default_author=None)["maatlog"]["author_summaries"]

    assert summaries == ()


def test_a_post_without_authors_falls_back_to_the_default_author(make_project: ProjectFactory) -> None:
    files = {
        **RAIL_PROJECT,
        "post.md": RAIL_PROJECT["post.md"].replace("maatlog-authors: [bob, alice]\n", ""),
    }
    result = make_project(files=files, theme="maatlog-default", config=RAIL_CONFIG).build()
    context: dict[str, Any] = {}
    inject_maatlog_page_context(result.app, "post", "page.html", context, None)

    assert [item["slug"] for item in context["maatlog"]["author_summaries"]] == ["alice"]


def test_an_unknown_default_author_fails_the_build(make_project: ProjectFactory) -> None:
    from maatlog.errors import MaatlogBuildError

    site = make_project(
        files=RAIL_PROJECT, theme="maatlog-default", config={**RAIL_CONFIG, "maatlog_default_author": "carol"}
    )

    with pytest.raises(MaatlogBuildError) as excinfo:
        site.build()

    assert [item.code for item in excinfo.value.diagnostics] == ["maatlog.config.invalid"]


PAGED_PROJECT = {
    "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-authors: [bob]
---
# One

Body.
""",
    "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
maatlog-authors: [bob]
---
# Two

Body.
""",
}


def test_author_archive_page_two_summarises_that_author_not_the_default(
    make_project: ProjectFactory,
) -> None:
    from maatlog.extension import collect_archive_pages

    result = make_project(
        files=PAGED_PROJECT,
        theme="maatlog-default",
        config={**RAIL_CONFIG, "maatlog_page_size": 1},
    ).build()
    contexts = {name: context for name, context, _ in collect_archive_pages(result.app)}

    summaries = contexts["blog/author/bob/page/2"]["maatlog"]["author_summaries"]
    assert [item["slug"] for item in summaries] == ["bob"]


def test_profile_page_has_no_author_summary(make_project: ProjectFactory) -> None:
    from maatlog.extension import collect_archive_pages

    result = make_project(
        files=PAGED_PROJECT,
        theme="maatlog-default",
        config={**RAIL_CONFIG, "maatlog_author_profiles": {"bob": {"bio_short": "Writer."}}},
    ).build()
    contexts = {name: context for name, context, _ in collect_archive_pages(result.app)}

    assert contexts["blog/author/bob"]["maatlog"]["page_kind"] == "profile"
    assert contexts["blog/author/bob"]["maatlog"]["author_summaries"] == ()


def test_tag_archive_summarises_the_default_author(make_project: ProjectFactory) -> None:
    from maatlog.extension import collect_archive_pages

    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    contexts = {name: context for name, context, _ in collect_archive_pages(result.app)}

    assert [item["slug"] for item in contexts["blog"]["maatlog"]["author_summaries"]] == ["alice"]


def _render_summary(result: Any, summaries: list[dict[str, Any]], page_kind: str = "post") -> str:
    """author-summary.html を単体でレンダリングする。"""
    templates = result.app.builder.templates
    template = templates.environment.get_template("maatlog/components/author-summary.html")
    return template.render(
        maatlog={"author_summaries": summaries, "page_kind": page_kind},
        _=_passthrough_text,
    )


def _passthrough_text(text: str) -> str:
    return text


def _summary_dict(slug: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": slug,
        "display_name": slug.title(),
        "avatar_url": None,
        "initials": slug[0].upper(),
        "bio_short": None,
        "links": [],
        "profile_url": f"blog/author/{slug}.html",
    }
    base.update(overrides)
    return base


def test_author_summary_renders_nothing_without_summaries(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()

    assert _render_summary(result, []).strip() == ""


def test_author_summary_shows_at_most_two_authors_inline(make_project: ProjectFactory) -> None:
    from conftest import HtmlPage

    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    html = _render_summary(result, [_summary_dict(name) for name in ("a", "b", "c", "d")])
    page = HtmlPage(html)
    inline_html, _, _ = html.partition("<details")

    assert inline_html.count('class="maatlog-author-summary-card"') == 2
    assert len(page.select(".maatlog-author-summary-more .maatlog-author-summary-card")) == 2
    assert "+2 authors" in html


def test_author_summary_uses_singular_for_one_hidden_author(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    html = _render_summary(result, [_summary_dict(name) for name in ("a", "b", "c")])

    assert "<summary>+1 author</summary>" in html
    assert "<summary>+1 authors</summary>" not in html


def test_author_summary_uses_initials_without_an_avatar(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    html = _render_summary(result, [_summary_dict("alice")])

    assert '<span class="maatlog-author-summary-avatar-initials" aria-hidden="true">A</span>' in html
    assert "maatlog-author-summary-avatar-image" not in html


def test_author_summary_omits_the_profile_link_without_a_url(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    html = _render_summary(result, [_summary_dict("alice", profile_url="")])

    assert "maatlog-author-summary-profile-link" not in html


def test_toc_is_a_nav_landmark(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    page = result.html("post.html")

    assert '<nav class="maatlog-toc"' in page.text
    assert '<aside class="maatlog-toc"' not in page.text


def test_right_rail_wraps_the_summary_and_the_toc(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    page = result.html("post.html")

    rail = page.select_one(".maatlog-right-rail[data-maatlog-component='right-rail']")
    assert rail is not None
    rail_pos = page.text.find('<div class="maatlog-right-rail"')
    summary_pos = page.text.find('<section class="maatlog-author-summary"')
    toc_pos = page.text.find('<nav class="maatlog-toc"')
    assert rail_pos != -1 and summary_pos != -1 and toc_pos != -1
    assert rail_pos < summary_pos < toc_pos


def test_rail_stands_up_on_a_page_without_a_toc(make_project: ProjectFactory) -> None:
    result = make_project(files=RAIL_PROJECT, theme="maatlog-default", config=RAIL_CONFIG).build()
    page = result.html("about.html")

    # about.rst は見出しが 1 つだけなので TOC は立たない。
    assert page.select_one(".maatlog-toc") is None
    assert page.select_one(".maatlog-author-summary") is not None
    assert page.select_one(".maatlog-layout-has-rail") is not None
    assert page.select_one(".maatlog-layout-has-toc") is None
    assert page.select_one(".maatlog-layout-has-author-summary") is not None


def test_no_rail_without_a_toc_and_without_a_summary(make_project: ProjectFactory) -> None:
    result = make_project(
        files=RAIL_PROJECT, theme="maatlog-default", config={**RAIL_CONFIG, "maatlog_default_author": None}
    ).build()
    page = result.html("about.html")

    assert page.select_one(".maatlog-right-rail") is None
    assert page.select_one(".maatlog-layout-has-rail") is None

"""Issue #60: archive filter DOM contract and runtime registration."""

from __future__ import annotations

import json

import pytest
from conftest import ProjectFactory

FILTER_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: filter-hello
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx, data-analysis]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: Filter fixture.
---
# Filter Hello

Body for archive filter contract.
""",
}

# Labels may contain Japanese and spaces; ids stay lowercase taxonomy keys.
FILTER_CONFIG = {
    "maatlog_tags": {"sphinx": "Sphinx", "data-analysis": "データ 分析"},
    "maatlog_categories": {"engineering": "Engineering"},
    "maatlog_authors": {"alice": "Alice"},
}


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_card_exposes_machine_readable_taxonomy_ids(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=FILTER_PROJECT, theme=theme, config=FILTER_CONFIG).build()
    archive = result.html("blog.html")
    card = archive.select_one(".maatlog-post-card")
    assert card is not None

    tags = json.loads(card["data-maatlog-tags"])
    categories = json.loads(card["data-maatlog-categories"])
    authors = json.loads(card["data-maatlog-authors"])

    assert tags == ["sphinx", "data-analysis"]
    assert categories == ["engineering"]
    assert authors == ["alice"]


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_archive_filter_toolbar_separates_id_and_label(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=FILTER_PROJECT, theme=theme, config=FILTER_CONFIG).build()
    archive = result.html("blog.html")

    assert 'data-maatlog-component="archive-filter"' in archive
    toolbar = archive.select_one('[data-maatlog-component="archive-filter"]')
    assert toolbar is not None

    assert archive.select_one('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="sphinx"]') is not None
    assert (
        archive.select_one('[data-maatlog-filter-axis="tag"] [data-maatlog-filter-value="data-analysis"]') is not None
    )
    assert (
        archive.select_one('[data-maatlog-filter-axis="category"] [data-maatlog-filter-value="engineering"]')
        is not None
    )
    assert archive.select_one('[data-maatlog-filter-axis="author"] [data-maatlog-filter-value="alice"]') is not None
    assert archive.select_one(".maatlog-filter-reset") is not None
    assert "No matching posts." in archive.text
    # Display label (not id) may include Japanese and spaces
    assert "データ 分析" in archive.text


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_archive_filter_is_registered_in_theme_runtime(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=FILTER_PROJECT, theme=theme, config=FILTER_CONFIG).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'registerEnhancer("archive-filter"' in script
    assert "data-maatlog-tags" in script
    assert "maatlog:content-added" in script
    assert "No matching posts." in script or "maatlog-archive-empty-filtered" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_css_defeats_author_display_for_hidden(make_project: ProjectFactory, theme: str) -> None:
    """``hidden`` must win over any author ``display`` rule (Issue #60 H-1)."""
    result = make_project(files=FILTER_PROJECT, theme=theme, config=FILTER_CONFIG).build()
    css = result.asset("_static/maatlog.css").read_text(encoding="utf-8")

    assert "[hidden] {" in css
    assert "display: none !important;" in css


# ``data-analysis`` rides the newest post only, so page 2 must never advertise it.
PAGINATED_PROJECT = {
    "rare.md": """---
maatlog-post: true
maatlog-slug: rare-newest
maatlog-published-at: 2026-07-31T12:00:00Z
maatlog-tags: [data-analysis]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: Newest.
---
# Rare Newest

Only post carrying data-analysis.
""",
    "common.md": """---
maatlog-post: true
maatlog-slug: common-older
maatlog-published-at: 2026-07-30T12:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: Older.
---
# Common Older

Older post.
""",
}


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toolbar_chips_come_from_this_pages_population(make_project: ProjectFactory, theme: str) -> None:
    """Page 2 must not advertise a taxonomy that only page 1 carries."""
    config = {**FILTER_CONFIG, "maatlog_page_size": 1}
    result = make_project(files=PAGINATED_PROJECT, theme=theme, config=config).build()

    page_one = result.html("blog.html")
    page_two = result.html("blog/page/2.html")

    assert page_one.select_one('[data-maatlog-filter-value="data-analysis"]') is not None
    assert page_one.select_one('[data-maatlog-filter-value="sphinx"]') is None

    assert page_two.select_one('[data-maatlog-filter-value="sphinx"]') is not None
    assert page_two.select_one('[data-maatlog-filter-value="data-analysis"]') is None


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_empty_message_is_a_live_region(make_project: ProjectFactory, theme: str) -> None:
    """Filtering to zero results has no URL change and no focus move (WCAG 4.1.3)."""
    result = make_project(files=FILTER_PROJECT, theme=theme, config=FILTER_CONFIG).build()
    archive = result.html("blog.html")

    empty = archive.select_one(".maatlog-archive-empty-filtered")
    assert empty is not None
    assert empty["role"] == "status"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toolbar_is_gated_on_the_theme_runtime(make_project: ProjectFactory, theme: str) -> None:
    """The toolbar follows the ``.maatlog-js`` pattern of the theme toggle."""
    result = make_project(files=FILTER_PROJECT, theme=theme, config=FILTER_CONFIG).build()
    css = result.asset("_static/maatlog.css").read_text(encoding="utf-8")

    assert ".maatlog-js .maatlog-archive-filter {" in css

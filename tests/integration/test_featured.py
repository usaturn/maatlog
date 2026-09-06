"""Integration tests for configured featured post selection (maatlog_featured_posts)."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from conftest import BuildResult, HtmlPage, ProjectFactory

from maatlog.errors import MaatlogBuildError
from maatlog.extension import collect_archive_pages
from maatlog.feeds import ATOM
from maatlog.views import FEATURED_LIMIT, relative_page_url_for

_FIVE = ("oldest", "mid", "newer", "new", "newest")


def _published_markdown(slug: str, *, day: int, extra: str = "", published_at: str | None = None) -> str:
    extra_line = f"{extra}\n" if extra else ""
    when = published_at if published_at is not None else f"2026-07-{day:02d}T09:00:00Z"
    return f"---\nmaatlog-post: true\nmaatlog-slug: {slug}\nmaatlog-published-at: {when}\n{extra_line}---\n# {slug}\n"


def _posts(*slugs: str, extra: str = "") -> dict[str, str]:
    return {
        f"{slug}.md": _published_markdown(slug, day=index, extra=extra) for index, slug in enumerate(slugs, start=1)
    }


def _dedicated_home(*slugs: str, extra: str = "") -> dict[str, str]:
    return {"index.rst": "Home\n====\n", **_posts(*slugs, extra=extra)}


def _card_slugs(page: HtmlPage, selector: str) -> list[str | None]:
    return [card.get("data-slug") for card in page.select(selector)]


def _featured_slugs(page: HtmlPage) -> list[str | None]:
    return _card_slugs(page, ".maatlog-post-featured .maatlog-post-card")


def _latest_slugs(page: HtmlPage) -> list[str | None]:
    return _card_slugs(page, ".maatlog-post-grid .maatlog-post-card")


def _draft_markdown(slug: str) -> str:
    return f"---\nmaatlog-post: true\nmaatlog-slug: {slug}\n---\n# {slug}\n"


def _featured_title_href(page: HtmlPage, slug: str) -> str:
    link = page.select_one(f".maatlog-post-featured .maatlog-post-card[data-slug='{slug}'] .maatlog-post-card-title a")
    assert link is not None
    return link["href"]


def _assert_unpublished(error: MaatlogBuildError, slug: str) -> None:
    matching = [item for item in error.diagnostics if item.code == "maatlog.featured.unpublished"]
    assert matching
    assert matching[0].field == "maatlog_featured_posts"
    assert matching[0].value == repr(slug)


def _atom_entries(result: BuildResult) -> dict[str, tuple[str | None, ...]]:
    outdir = Path(result.app.outdir)
    feeds: dict[str, tuple[str | None, ...]] = {}
    for path in sorted(outdir.rglob("atom.xml")):
        root = ET.fromstring(path.read_bytes())
        feeds[path.relative_to(outdir).as_posix()] = tuple(
            entry.findtext(f"{{{ATOM}}}id") for entry in root.findall(f"{{{ATOM}}}entry")
        )
    return feeds


@pytest.mark.parametrize(
    "featured_posts",
    [pytest.param(None, id="unspecified"), pytest.param([], id="empty")],
)
def test_unspecified_and_empty_featured_use_newest_posts(
    make_project: ProjectFactory,
    featured_posts: list[str] | None,
) -> None:
    config: dict[str, object] = {"maatlog_home_docname": "index"}
    if featured_posts is not None:
        config["maatlog_featured_posts"] = featured_posts
    result = make_project(files=_dedicated_home(*_FIVE), config=config).build()
    home = result.html("index.html")
    assert _featured_slugs(home) == ["newest", "new", "newer"]


def test_one_specified_post_is_filled_without_duplicating(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_dedicated_home(*_FIVE),
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
    ).build()
    home = result.html("index.html")
    featured = _featured_slugs(home)
    latest = _latest_slugs(home)
    assert featured == ["oldest", "newest", "new"]
    assert "oldest" not in latest
    assert len(featured) == FEATURED_LIMIT


def test_home_uses_configured_featured_order(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_dedicated_home(*_FIVE),
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest", "newest"]},
    ).build()
    home = result.html("index.html")
    featured = _featured_slugs(home)
    latest = _latest_slugs(home)
    assert featured == ["oldest", "newest", "new"]
    assert "oldest" not in latest
    assert "newest" not in latest


def test_fourth_specified_post_remains_in_latest(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_dedicated_home(*_FIVE),
        config={
            "maatlog_home_docname": "index",
            "maatlog_featured_posts": ["oldest", "mid", "newer", "new"],
        },
    ).build()
    home = result.html("index.html")
    featured = _featured_slugs(home)
    latest = _latest_slugs(home)
    assert featured == ["oldest", "mid", "newer"]
    assert "new" in latest


def test_two_published_posts_show_two_featured_cards(make_project: ProjectFactory) -> None:
    files = {
        **_dedicated_home("older", "newer"),
        "draft.md": """---
maatlog-post: true
maatlog-slug: draft
---
# draft
""",
    }
    result = make_project(files=files, config={"maatlog_home_docname": "index"}).build()
    home = result.html("index.html")
    assert _featured_slugs(home) == ["newer", "older"]
    assert _latest_slugs(home) == []


def test_page_size_caps_latest_not_featured(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_dedicated_home(*_FIVE),
        config={"maatlog_home_docname": "index", "maatlog_page_size": 1},
    ).build()
    home = result.html("index.html")
    assert len(_featured_slugs(home)) == FEATURED_LIMIT
    assert len(_latest_slugs(home)) == 1


def test_featuring_the_home_document_fails_with_self(make_project: ProjectFactory) -> None:
    files = {
        "welcome.md": _published_markdown("welcome", day=2),
        "other.md": _published_markdown("other", day=1),
    }
    with pytest.raises(MaatlogBuildError) as caught:
        make_project(
            files=files,
            config={"maatlog_home_docname": "welcome", "maatlog_featured_posts": ["welcome"]},
        ).build()
    matching = [item for item in caught.value.diagnostics if item.code == "maatlog.featured.self"]
    assert matching
    assert matching[0].field == "maatlog_featured_posts"


def test_archive_home_keeps_window_when_pin_is_outside(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_posts("pinned", "mid", "new", "newest"),
        config={"maatlog_page_size": 2, "maatlog_featured_posts": ["pinned"]},
    ).build()
    pages = list(collect_archive_pages(result.app))
    home = next(item for item in pages if item[1]["maatlog"]["archive"]["is_home"])
    maatlog = home[1]["maatlog"]
    featured_slugs = [card["slug"] for card in maatlog["featured"]]
    latest_slugs = [card["slug"] for card in maatlog["latest"]]
    post_slugs = [card["slug"] for card in maatlog["posts"]]
    assert featured_slugs == ["pinned", "newest", "new"]
    assert len(maatlog["posts"]) == result.app.config.maatlog_page_size
    assert "pinned" not in post_slugs
    assert all(slug not in featured_slugs for slug in latest_slugs)


def test_taxonomy_archive_featured_and_latest_are_empty(make_project: ProjectFactory) -> None:
    result = make_project(
        files=_dedicated_home(*_FIVE, extra="maatlog-tags: [sphinx]"),
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
    ).build()
    pages = list(collect_archive_pages(result.app))
    tag_pages = [context for _name, context, _template in pages if context["maatlog"]["archive"]["kind"] == "tag"]
    assert tag_pages
    for context in tag_pages:
        assert context["maatlog"]["featured"] == ()
        assert context["maatlog"]["latest"] == ()


def test_feed_entries_do_not_change_when_featured_is_configured(make_project: ProjectFactory) -> None:
    files = _dedicated_home(*_FIVE, extra="maatlog-tags: [sphinx]")
    without = make_project(files=files, config={"maatlog_home_docname": "index"}).build()
    pinned = make_project(
        files=files,
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
    ).build()
    assert _atom_entries(pinned) == _atom_entries(without)


def test_incremental_config_change_pins_oldest(make_project: ProjectFactory) -> None:
    project = make_project(files=_dedicated_home(*_FIVE), config={"maatlog_home_docname": "index"})
    first = project.build(reuse_environment=False)
    assert _featured_slugs(first.html("index.html")) == ["newest", "new", "newer"]

    project.config["maatlog_featured_posts"] = ["oldest"]
    project.rewrite_conf()
    second = project.build(reuse_environment=True)
    assert _featured_slugs(second.html("index.html"))[0] == "oldest"


def test_incremental_featured_draft_is_unpublished(make_project: ProjectFactory) -> None:
    project = make_project(
        files=_dedicated_home(*_FIVE),
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
    )
    first = project.build(reuse_environment=False)
    assert _featured_slugs(first.html("index.html"))[0] == "oldest"

    project.write("oldest.md", _draft_markdown("oldest"))
    with pytest.raises(MaatlogBuildError) as caught:
        project.build(reuse_environment=True)
    _assert_unpublished(caught.value, "oldest")


def test_incremental_scheduled_featured_becomes_published(make_project: ProjectFactory) -> None:
    files = _dedicated_home(*_FIVE)
    files["oldest.md"] = _published_markdown("oldest", day=1, published_at="2026-08-15T09:00:00Z")
    project = make_project(
        files=files,
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
    )
    with pytest.raises(MaatlogBuildError) as caught:
        project.build(reuse_environment=False)
    _assert_unpublished(caught.value, "oldest")

    project.write("oldest.md", _published_markdown("oldest", day=1))
    result = project.build(reuse_environment=True)
    assert _featured_slugs(result.html("index.html"))[0] == "oldest"


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_pinned_card_href_follows_html_and_dirhtml(make_project: ProjectFactory, builder: str) -> None:
    result = make_project(
        files=_dedicated_home(*_FIVE),
        config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
        builder=builder,
    ).build()
    home = result.html("index.html")
    href = _featured_title_href(home, "oldest")
    expected = relative_page_url_for(result.app.builder, "index", "oldest")
    assert href == expected
    if builder == "html":
        assert href == "oldest.html"
    else:
        assert href == "oldest/"


def test_expired_explicit_featured_is_unpublished(make_project: ProjectFactory) -> None:
    files = _dedicated_home(*_FIVE)
    files["oldest.md"] = _published_markdown("oldest", day=1, extra="maatlog-expires-at: 2026-07-31T09:00:00Z")
    with pytest.raises(MaatlogBuildError) as caught:
        make_project(
            files=files,
            config={"maatlog_home_docname": "index", "maatlog_featured_posts": ["oldest"]},
        ).build()
    _assert_unpublished(caught.value, "oldest")

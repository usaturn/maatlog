"""Integration tests for MaatLog Atom feed generation (html / dirhtml)."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from conftest import ProjectFactory

from maatlog.feeds import ATOM

FEED_PROJECT = {
    "hello.md": """---
maatlog-post: true
maatlog-slug: hello
maatlog-published-at: 2026-07-15T12:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: Hello blurb.
---
# Hello

Body with a <a href="more.html">relative link</a>.
""",
    "external.md": """---
maatlog-post: true
maatlog-slug: external
maatlog-published-at: 2026-07-10T12:00:00Z
maatlog-tags: [sphinx]
maatlog-excerpt: External summary
maatlog-external-url: https://publisher.example/article
---
# External

Hidden source body.
""",
    "draft.md": """---
maatlog-post: true
maatlog-slug: draft-only
maatlog-tags: [hidden]
---
# Draft

Should not appear in feeds.
""",
}

MANY_POSTS = {
    f"p{i}.md": f"""---
maatlog-post: true
maatlog-slug: post-{i}
maatlog-published-at: 2026-07-{i:02d}T12:00:00Z
maatlog-tags: [bulk]
---
# Post {i}

Body {i}.
"""
    for i in range(1, 6)
}


def _parse_atom(path: Path) -> ET.Element:
    return ET.fromstring(path.read_bytes())


def _entry_titles(root: ET.Element) -> list[str | None]:
    return [entry.findtext(f"{{{ATOM}}}title") for entry in root.findall(f"{{{ATOM}}}entry")]


@pytest.mark.parametrize(
    ("builder", "hello_page_url"),
    [
        ("html", "https://example.com/docs/hello.html"),
        ("dirhtml", "https://example.com/docs/hello/"),
    ],
)
def test_global_and_taxonomy_feeds(
    make_project: ProjectFactory,
    builder: str,
    hello_page_url: str,
) -> None:
    result = make_project(
        files=FEED_PROJECT,
        builder=builder,
        config={"html_baseurl": "https://example.com/docs/"},
    ).build()

    expected = (
        "blog/atom.xml",
        "blog/tag/sphinx/atom.xml",
        "blog/category/engineering/atom.xml",
        "blog/author/alice/atom.xml",
        "blog/month/2026-07/atom.xml",
    )
    for relative in expected:
        path = result.path(relative)
        assert path.is_file(), relative
        root = _parse_atom(path)
        assert root.tag == f"{{{ATOM}}}feed"
        titles = _entry_titles(root)
        assert "Draft" not in titles
        assert all(title is not None for title in titles)

    # Draft-only tag must not produce a feed.
    assert not result.path("blog/tag/hidden/atom.xml").exists()

    global_root = _parse_atom(result.path("blog/atom.xml"))
    assert _entry_titles(global_root) == ["Hello", "External"]

    hello_entry = global_root.findall(f"{{{ATOM}}}entry")[0]
    content = hello_entry.find(f"{{{ATOM}}}content")
    assert content is not None
    assert content.get("type") == "html"
    assert content.text is not None
    # Relative href absolutized against the builder page URL.
    if builder == "html":
        assert 'href="https://example.com/docs/more.html"' in content.text
    else:
        assert f'href="{hello_page_url}more.html"' in content.text

    external_entry = global_root.findall(f"{{{ATOM}}}entry")[1]
    assert external_entry.findtext(f"{{{ATOM}}}content") == "<p>External summary</p>"
    related = [link for link in external_entry.findall(f"{{{ATOM}}}link") if link.get("rel") == "related"]
    assert len(related) == 1
    assert "Hidden source body" not in result.path("blog/atom.xml").read_text(encoding="utf-8")


def test_feed_limit_truncates_entries(make_project: ProjectFactory) -> None:
    result = make_project(
        files=MANY_POSTS,
        config={
            "html_baseurl": "https://example.com/",
            "maatlog_feed_limit": 2,
        },
    ).build()
    root = _parse_atom(result.path("blog/atom.xml"))
    # published order is newest first: post-5, post-4, ...
    assert _entry_titles(root) == ["Post 5", "Post 4"]
    tag_root = _parse_atom(result.path("blog/tag/bulk/atom.xml"))
    assert len(tag_root.findall(f"{{{ATOM}}}entry")) == 2


def test_taxonomy_feed_preserves_global_published_order(make_project: ProjectFactory) -> None:
    result = make_project(
        files=MANY_POSTS,
        config={"html_baseurl": "https://example.com/", "maatlog_feed_limit": 20},
    ).build()
    global_titles = _entry_titles(_parse_atom(result.path("blog/atom.xml")))
    taxonomy_titles = _entry_titles(_parse_atom(result.path("blog/tag/bulk/atom.xml")))
    assert taxonomy_titles == global_titles


def test_disabled_feeds_write_nothing(make_project: ProjectFactory) -> None:
    result = make_project(
        files=FEED_PROJECT,
        config={
            "html_baseurl": "https://example.com/",
            "maatlog_generate_feeds": False,
        },
    ).build()
    assert list(Path(result.app.outdir).rglob("atom.xml")) == []


def test_empty_global_feed_when_no_published_posts(make_project: ProjectFactory) -> None:
    result = make_project(
        files={
            "draft.md": """---
maatlog-post: true
maatlog-slug: only-draft
---
# Draft

Not published.
""",
        },
        config={"html_baseurl": "https://example.com/"},
    ).build()
    path = result.path("blog/atom.xml")
    assert path.is_file()
    root = _parse_atom(path)
    assert root.findall(f"{{{ATOM}}}entry") == []
    # No taxonomy feeds without published members.
    assert not result.path("blog/tag").exists() or not list(result.path("blog/tag").rglob("atom.xml"))


PARALLEL_FEED_PROJECT = {
    f"post-{i:02d}.rst": f""":maatlog-post: true
:maatlog-slug: parallel-{i:02d}
:maatlog-published-at: 2026-07-{i + 1:02d}T00:00:00Z
:maatlog-tags: shared
:maatlog-categories: engineering
:maatlog-authors: alice

Parallel {i}
==========

Parallel body marker {i}.
"""
    for i in range(8)
}


def test_parallel_atom_bytes_match_serial(make_project: ProjectFactory) -> None:
    from maatlog.html_metadata import BODY_FRAGMENT_DIRNAME

    config = {"html_baseurl": "https://example.com/docs/"}
    serial = make_project(files=PARALLEL_FEED_PROJECT, config=config).build(parallel=1)
    parallel = make_project(files=PARALLEL_FEED_PROJECT, config=config).build(parallel=4)

    relatives = (
        "blog/atom.xml",
        "blog/tag/shared/atom.xml",
        "blog/category/engineering/atom.xml",
        "blog/author/alice/atom.xml",
        "blog/month/2026-07/atom.xml",
    )
    for relative in relatives:
        assert serial.path(relative).read_bytes() == parallel.path(relative).read_bytes()

    parallel_xml = parallel.path("blog/atom.xml").read_text(encoding="utf-8")
    for i in range(8):
        assert f"Parallel body marker {i}." in parallel_xml

    assert not (Path(serial.app.doctreedir) / BODY_FRAGMENT_DIRNAME).exists()
    assert not (Path(parallel.app.doctreedir) / BODY_FRAGMENT_DIRNAME).exists()

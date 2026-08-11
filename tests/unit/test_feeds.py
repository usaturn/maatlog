"""Unit coverage for MaatLog Atom feed projection and deterministic XML."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from maatlog.feeds import (
    ATOM,
    AtomEntry,
    AtomFeed,
    atom_entry,
    atom_feed,
    default_generator,
    feed_author,
    feed_title,
    serialize_atom,
)
from maatlog.model import Post, PublicationStatus
from maatlog.urls import PostUrls, post_urls

PostFactory = Callable[..., Post]

TOKYO = timezone(timedelta(hours=9))


@pytest.fixture
def post() -> PostFactory:
    def factory(**overrides: Any) -> Post:
        values: dict[str, Any] = {
            "docname": "blog/hello",
            "source_path": "blog/hello.md",
            "title": "Hello",
            "slug": "hello",
            "published_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            "expires_at": None,
            "tags": ("release",),
            "categories": ("news",),
            "authors": ("maat",),
            "excerpt": None,
            "image_uri": None,
            "canonical_url": None,
            "external_url": None,
            "status": PublicationStatus.PUBLISHED,
        }
        values.update(overrides)
        return Post(**values)

    return factory


@pytest.fixture
def internal_urls() -> PostUrls:
    return post_urls(
        page_url="https://example.com/blog/hello/",
        canonical=None,
        external=None,
    )


@pytest.fixture
def external_urls() -> PostUrls:
    return post_urls(
        page_url="https://example.com/blog/external/",
        canonical=None,
        external="https://publisher.example/article",
    )


@pytest.fixture
def sample_entry(post: PostFactory, internal_urls: PostUrls) -> AtomEntry:
    return atom_entry(
        post(excerpt="Blurb", tags=("sphinx",), categories=("docs",)),
        urls=internal_urls,
        body_html='<p>Body <a href="more.html">more</a></p>',
        tag_labels={"sphinx": "Sphinx"},
        category_labels={"docs": "Documentation"},
    )


@pytest.fixture
def feed(sample_entry: AtomEntry) -> AtomFeed:
    return atom_feed(
        identifier="https://example.com/blog/atom.xml",
        title="Demo Project",
        self_url="https://example.com/blog/atom.xml",
        alternate_url="https://example.com/blog/",
        author="Demo Author",
        entries=(sample_entry,),
        build_time=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
    )


def _parse(xml: bytes) -> ET.Element:
    return ET.fromstring(xml)


def _child(parent: ET.Element, local: str) -> ET.Element:
    element = parent.find(f"{{{ATOM}}}{local}")
    assert element is not None, f"missing {{{ATOM}}}{local}"
    return element


def _children(parent: ET.Element, local: str) -> list[ET.Element]:
    return parent.findall(f"{{{ATOM}}}{local}")


def test_serialize_has_xml_declaration_and_atom_namespace(feed: AtomFeed) -> None:
    xml = serialize_atom(feed)
    assert xml.startswith(b"<?xml version=")
    assert b"encoding='utf-8'" in xml or b'encoding="utf-8"' in xml
    root = _parse(xml)
    assert root.tag == f"{{{ATOM}}}feed"
    assert root.get("xmlns") is None or root.get("xmlns") == ATOM


def test_feed_metadata_elements(feed: AtomFeed) -> None:
    root = _parse(serialize_atom(feed))
    assert _child(root, "id").text == "https://example.com/blog/atom.xml"
    assert _child(root, "title").text == "Demo Project"
    assert _child(root, "updated").text == "2026-08-01T12:00:00+00:00"
    assert _child(root, "generator").text == default_generator()
    assert default_generator().startswith("MaatLog ")

    links = _children(root, "link")
    assert len(links) == 2
    assert links[0].attrib == {
        "href": "https://example.com/blog/atom.xml",
        "rel": "self",
        "type": "application/atom+xml",
    }
    assert links[1].attrib == {
        "href": "https://example.com/blog/",
        "rel": "alternate",
        "type": "text/html",
    }

    author = _child(root, "author")
    assert _child(author, "name").text == "Demo Author"


def test_empty_feed_updated_uses_build_time() -> None:
    build_time = datetime(2026, 7, 1, 9, 30, tzinfo=TOKYO)
    feed = atom_feed(
        identifier="https://example.com/blog/atom.xml",
        title="Empty",
        self_url="https://example.com/blog/atom.xml",
        alternate_url="https://example.com/blog/",
        author="Empty",
        entries=(),
        build_time=build_time,
    )
    assert feed.updated == build_time
    root = _parse(serialize_atom(feed))
    assert _child(root, "updated").text == "2026-07-01T09:30:00+09:00"
    assert _children(root, "entry") == []


def test_feed_updated_is_newest_entry_published(post: PostFactory, internal_urls: PostUrls) -> None:
    older = atom_entry(
        post(
            slug="older",
            title="Older",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            tags=(),
            categories=(),
            authors=(),
        ),
        urls=internal_urls,
        body_html="<p>o</p>",
    )
    newer = atom_entry(
        post(
            slug="newer",
            title="Newer",
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            tags=(),
            categories=(),
            authors=(),
        ),
        urls=internal_urls,
        body_html="<p>n</p>",
    )
    # Entries may arrive newest-first; updated still tracks the maximum published.
    feed = atom_feed(
        identifier="https://example.com/atom.xml",
        title="T",
        self_url="https://example.com/atom.xml",
        alternate_url="https://example.com/",
        author="A",
        entries=(older, newer),
        build_time=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert feed.updated == datetime(2026, 8, 1, tzinfo=UTC)


def test_feed_limit_truncates_published_sequence(post: PostFactory, internal_urls: PostUrls) -> None:
    entries = tuple(
        atom_entry(
            post(
                slug=f"p{i}",
                title=f"P{i}",
                published_at=datetime(2026, 8, i, tzinfo=UTC),
                tags=(),
                categories=(),
                authors=(),
            ),
            urls=internal_urls,
            body_html=f"<p>{i}</p>",
        )
        for i in range(1, 5)
    )
    feed = atom_feed(
        identifier="https://example.com/atom.xml",
        title="T",
        self_url="https://example.com/atom.xml",
        alternate_url="https://example.com/",
        author="A",
        entries=entries,
        build_time=datetime(2026, 1, 1, tzinfo=UTC),
        limit=2,
    )
    assert len(feed.entries) == 2
    assert [entry.title for entry in feed.entries] == ["P1", "P2"]


def test_external_entry_uses_excerpt_not_source_body(
    post: PostFactory,
    external_urls: PostUrls,
) -> None:
    entry = atom_entry(
        post(
            title="External Post",
            excerpt="Summary",
            external_url="https://publisher.example/article",
            tags=(),
            categories=(),
            authors=(),
        ),
        urls=external_urls,
        body_html="private body",
    )
    feed = atom_feed(
        identifier="https://example.com/blog/atom.xml",
        title="Demo",
        self_url="https://example.com/blog/atom.xml",
        alternate_url="https://example.com/blog/",
        author="Demo",
        entries=(entry,),
        build_time=datetime(2026, 8, 1, tzinfo=UTC),
    )
    xml = serialize_atom(feed)
    assert b"Summary" in xml
    assert b"private body" not in xml
    assert b'rel="related"' in xml

    root = _parse(xml)
    entry_el = _children(root, "entry")[0]
    assert _child(entry_el, "id").text == external_urls.canonical_url
    links = _children(entry_el, "link")
    assert links[0].attrib == {
        "href": "https://publisher.example/article",
        "rel": "alternate",
    }
    assert links[1].attrib == {
        "href": "https://example.com/blog/external/",
        "rel": "related",
    }
    content = _child(entry_el, "content")
    assert content.get("type") == "html"
    assert content.text == "<p>Summary</p>"
    summary = _child(entry_el, "summary")
    assert summary.get("type") == "text"
    assert summary.text == "Summary"


def test_internal_entry_uses_body_and_absolutizes_urls(
    post: PostFactory,
    internal_urls: PostUrls,
) -> None:
    entry = atom_entry(
        post(excerpt="Blurb", authors=("alice", "bob"), tags=("a",), categories=("b",)),
        urls=internal_urls,
        body_html='<p><a href="more.html">x</a><img src="/img.png"/></p>',
        tag_labels={"a": "A"},
        category_labels={"b": "B"},
    )
    assert entry.related_url is None
    assert entry.alternate_url == internal_urls.page_url
    assert entry.identifier == internal_urls.canonical_url
    assert 'href="https://example.com/blog/hello/more.html"' in entry.content_html
    assert 'src="https://example.com/img.png"' in entry.content_html

    root = _parse(
        serialize_atom(
            atom_feed(
                identifier="https://example.com/atom.xml",
                title="T",
                self_url="https://example.com/atom.xml",
                alternate_url="https://example.com/",
                author="A",
                entries=(entry,),
                build_time=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    )
    entry_el = _children(root, "entry")[0]
    assert _child(entry_el, "published").text == _child(entry_el, "updated").text
    authors = [_child(a, "name").text for a in _children(entry_el, "author")]
    assert authors == ["alice", "bob"]
    categories = _children(entry_el, "category")
    assert categories[0].attrib == {
        "term": "a",
        "label": "A",
        "scheme": "urn:maatlog:tag",
    }
    assert categories[1].attrib == {
        "term": "b",
        "label": "B",
        "scheme": "urn:maatlog:category",
    }
    assert b'rel="related"' not in ET.tostring(entry_el)


def test_entry_authors_use_display_names(
    post: PostFactory,
    internal_urls: PostUrls,
) -> None:
    entry = atom_entry(
        post(authors=("maat", "alice"), tags=(), categories=()),
        urls=internal_urls,
        body_html="<p>x</p>",
        author_labels={"maat": "Maat Team", "alice": "Alice"},
    )
    assert entry.authors == ("Maat Team", "Alice")

    # Missing labels fall back to the taxonomy ID.
    partial = atom_entry(
        post(authors=("maat", "unknown"), tags=(), categories=()),
        urls=internal_urls,
        body_html="<p>x</p>",
        author_labels={"maat": "Maat Team"},
    )
    assert partial.authors == ("Maat Team", "unknown")

    root = _parse(
        serialize_atom(
            atom_feed(
                identifier="https://example.com/atom.xml",
                title="T",
                self_url="https://example.com/atom.xml",
                alternate_url="https://example.com/",
                author="A",
                entries=(entry,),
                build_time=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    )
    entry_el = _children(root, "entry")[0]
    names = [_child(a, "name").text for a in _children(entry_el, "author")]
    assert names == ["Maat Team", "Alice"]


def test_entry_without_authors_omits_author_elements(
    post: PostFactory,
    internal_urls: PostUrls,
) -> None:
    entry = atom_entry(
        post(authors=(), tags=(), categories=(), excerpt=None),
        urls=internal_urls,
        body_html="<p>x</p>",
    )
    root = _parse(
        serialize_atom(
            atom_feed(
                identifier="https://example.com/atom.xml",
                title="T",
                self_url="https://example.com/atom.xml",
                alternate_url="https://example.com/",
                author="Project",
                entries=(entry,),
                build_time=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    )
    entry_el = _children(root, "entry")[0]
    assert _children(entry_el, "author") == []
    assert entry_el.find(f"{{{ATOM}}}summary") is None


def test_canonical_url_is_entry_id(post: PostFactory) -> None:
    urls = post_urls(
        page_url="https://example.com/blog/hello/",
        canonical="https://canonical.example/hello",
        external=None,
    )
    entry = atom_entry(post(), urls=urls, body_html="<p>x</p>")
    assert entry.identifier == "https://canonical.example/hello"


def test_datetime_keeps_offset_and_optional_microseconds(
    post: PostFactory,
    internal_urls: PostUrls,
) -> None:
    with_us = atom_entry(
        post(published_at=datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=TOKYO)),
        urls=internal_urls,
        body_html="<p>x</p>",
    )
    without_us = atom_entry(
        post(published_at=datetime(2026, 8, 1, 12, 0, 0, tzinfo=TOKYO), slug="b"),
        urls=internal_urls,
        body_html="<p>y</p>",
    )
    xml_with = serialize_atom(
        atom_feed(
            identifier="https://example.com/atom.xml",
            title="T",
            self_url="https://example.com/atom.xml",
            alternate_url="https://example.com/",
            author="A",
            entries=(with_us,),
            build_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    xml_without = serialize_atom(
        atom_feed(
            identifier="https://example.com/atom.xml",
            title="T",
            self_url="https://example.com/atom.xml",
            alternate_url="https://example.com/",
            author="A",
            entries=(without_us,),
            build_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    assert b"2026-08-01T12:00:00.123456+09:00" in xml_with
    assert b"2026-08-01T12:00:00+09:00" in xml_without
    assert b".000000" not in xml_without


def test_atom_is_byte_deterministic(feed: AtomFeed) -> None:
    assert serialize_atom(feed) == serialize_atom(feed)
    again = atom_feed(
        identifier=feed.identifier,
        title=feed.title,
        self_url=feed.self_url,
        alternate_url=feed.alternate_url,
        author=feed.author,
        entries=feed.entries,
        build_time=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        generator=feed.generator,
    )
    assert serialize_atom(feed) == serialize_atom(again)


def test_feed_title_and_author_helpers() -> None:
    assert feed_title("Project") == "Project"
    assert feed_title("Project", "Sphinx") == "Project — Sphinx"
    assert feed_author("Alice", "Project") == "Alice"
    assert feed_author("  ", "Project") == "Project"
    assert feed_author(None, "Project") == "Project"
    assert feed_author("", "Project") == "Project"


def test_content_html_is_xml_escaped_once(
    post: PostFactory,
    internal_urls: PostUrls,
) -> None:
    entry = atom_entry(
        post(excerpt=None, tags=(), categories=(), authors=()),
        urls=internal_urls,
        body_html="<p>a & b</p>",
    )
    xml = serialize_atom(
        atom_feed(
            identifier="https://example.com/atom.xml",
            title="T",
            self_url="https://example.com/atom.xml",
            alternate_url="https://example.com/",
            author="A",
            entries=(entry,),
            build_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    # XML text layer escapes once; HTML tags remain as escaped markup text.
    assert b"&amp;" in xml
    assert b"&amp;amp;" not in xml
    root = _parse(xml)
    content = _child(_children(root, "entry")[0], "content")
    assert content.text == "<p>a & b</p>"


def test_external_excerpt_special_chars_not_double_escaped(
    post: PostFactory,
    external_urls: PostUrls,
) -> None:
    entry = atom_entry(
        post(
            excerpt='a < b & "c"',
            external_url="https://publisher.example/article",
            tags=(),
            categories=(),
            authors=(),
        ),
        urls=external_urls,
        body_html="ignored",
    )
    # html.escape(quote=False) leaves double quotes; angle brackets and ampersand escape.
    assert entry.content_html == '<p>a &lt; b &amp; "c"</p>'

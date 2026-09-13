"""DOM and JSON assertions shared by social metadata tests."""

import json
from html.parser import HTMLParser
from typing import cast
from urllib.parse import urlsplit

from conftest import HtmlPage


class JsonLdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.bodies: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("type") == "application/ld+json":
            if self._parts is not None:
                raise AssertionError("nested JSON-LD script")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._parts is not None:
            self.bodies.append("".join(self._parts))
            self._parts = None

    def close(self) -> None:
        super().close()
        if self._parts is not None:
            raise AssertionError("unterminated JSON-LD script")


def open_graph_values(page: HtmlPage, property_name: str) -> list[str]:
    return [item["content"] for item in page.select(f'meta[property="{property_name}"]')]


def twitter_values(page: HtmlPage, name: str) -> list[str]:
    return [item["content"] for item in page.select(f'meta[name="{name}"]')]


def json_ld_bodies(page: HtmlPage) -> list[str]:
    parser = JsonLdCollector()
    parser.feed(page.text)
    parser.close()
    return parser.bodies


def json_ld_objects(page: HtmlPage) -> list[object]:
    return [json.loads(body) for body in json_ld_bodies(page)]


def assert_crawler_urls_are_absolute(page: HtmlPage) -> None:
    candidates = [
        *open_graph_values(page, "og:url"),
        *open_graph_values(page, "og:image"),
        *twitter_values(page, "twitter:image"),
    ]
    for payload in json_ld_objects(page):
        candidates.extend(_crawler_url_values(payload))
    for value in candidates:
        parsed = urlsplit(value)
        assert parsed.scheme in {"http", "https"} and parsed.netloc, value


def _crawler_url_values(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in cast("dict[str, object]", value).items():
            if key in {"url", "image", "sameAs"}:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, list):
                    found.extend(candidate for candidate in cast("list[object]", item) if isinstance(candidate, str))
            if isinstance(item, (dict, list)):
                found.extend(_crawler_url_values(cast("object", item)))
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            found.extend(_crawler_url_values(item))
    return found


def assert_no_social_metadata(page: HtmlPage) -> None:
    """Fail if the page carries any OG, X Card or JSON-LD output.

    Issue #208 connects the output boundary while every projector still returns an empty
    view, so no page may carry social metadata yet. The check is a prefix check, not a
    probe of one well-known property: a projector that emitted only ``og:title`` must
    fail too. ``HtmlPage`` matches attribute values exactly (see ``_parse_selector`` in
    ``conftest``), so prefix selectors such as ``meta[property^="og:"]`` are unavailable
    and the prefixes are matched against the rendered markup instead.
    """
    assert 'property="og:' not in page.text
    assert 'name="twitter:' not in page.text
    assert json_ld_objects(page) == []


#: The repeatable Open Graph properties MaatLog currently emits. A second occurrence
#: of any other emitted property means two code paths rendered the same head.
_REPEATABLE_OPEN_GRAPH = frozenset({"article:tag", "article:section"})


class MetaCollector(HTMLParser):
    """Collect every Open Graph property and X Card name on a page, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.open_graph: list[str] = []
        self.twitter: list[str] = []
        self.open_graph_items: list[tuple[str, str]] = []
        self.twitter_items: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = dict(attrs)
        property_name = attributes.get("property")
        if property_name is not None and property_name.startswith(("og:", "article:", "profile:")):
            self.open_graph.append(property_name)
            self.open_graph_items.append((property_name, cast("str", attributes.get("content", ""))))
        name = attributes.get("name")
        if name is not None and name.startswith("twitter:"):
            self.twitter.append(name)
            self.twitter_items.append((name, cast("str", attributes.get("content", ""))))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # The shared partial writes ``<meta ... />``; HTMLParser routes those here only.
        self.handle_starttag(tag, attrs)


def assert_no_crawler_urls(page: HtmlPage) -> None:
    """Fail if the page carries any crawler-facing absolute URL.

    Used where the build has no ``html_baseurl``: no projector may invent an ``og:url``,
    ``og:image`` or ``twitter:image``, and no JSON-LD object may carry a ``url`` or
    ``image`` key at any depth. Unlike :func:`assert_no_social_metadata` this survives
    every page lane emitting its own titles and descriptions, so it keeps stating what
    #206 AC12 actually requires.
    """
    for property_name in ("og:url", "og:image"):
        assert open_graph_values(page, property_name) == [], f"{property_name} without html_baseurl"
    assert twitter_values(page, "twitter:image") == [], "twitter:image without html_baseurl"
    for payload in json_ld_objects(page):
        assert _url_or_image_keys(payload) == [], "JSON-LD carries a URL without html_baseurl"


def _url_or_image_keys(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in cast("dict[str, object]", value).items():
            if key in {"url", "image"}:
                found.append(key)
            found.extend(_url_or_image_keys(item))
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            found.extend(_url_or_image_keys(item))
    return found


def assert_no_duplicate_social_metadata(page: HtmlPage) -> None:
    """Fail if one page emits the same metadata twice.

    The head is assembled once by ``maatlog_head``; a duplicate means a template or an
    incremental / parallel build path rendered it a second time. Repeatable Open Graph
    properties are excluded, and at most one JSON-LD script may appear per page.
    """
    collector = MetaCollector()
    collector.feed(page.text)
    collector.close()
    single_valued = [item for item in collector.open_graph if item not in _REPEATABLE_OPEN_GRAPH]
    assert len(single_valued) == len(set(single_valued)), f"duplicate Open Graph property: {single_valued}"
    assert len(collector.twitter) == len(set(collector.twitter)), f"duplicate X Card name: {collector.twitter}"
    assert len(json_ld_objects(page)) <= 1, "more than one JSON-LD script"

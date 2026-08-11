"""Absolute URL helpers for MaatLog feeds and HTML metadata."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .errors import Diagnostic, MaatlogBuildError

BASEURL_REQUIRED = "maatlog.feed.baseurl-required"
_PASSTHROUGH_SCHEMES = frozenset({"mailto", "tel", "data"})
_HREF_SRC = frozenset({"href", "src"})
_BASEURL_EXPECTED = "an absolute HTTP or HTTPS URL with a host and without userinfo, query, or fragment"


@dataclass(frozen=True, slots=True)
class PostUrls:
    """Resolved public URL roles for a single post."""

    page_url: str
    canonical_url: str
    external_url: str | None
    primary_url: str


def post_urls(page_url: str, canonical: str | None, external: str | None) -> PostUrls:
    """Build :class:`PostUrls` with canonical／primary fallbacks."""
    return PostUrls(
        page_url=page_url,
        canonical_url=canonical or page_url,
        external_url=external,
        primary_url=external or page_url,
    )


def validate_baseurl(url: str | None) -> str:
    """Validate and normalize Sphinx ``html_baseurl`` for feed generation.

    Requirements: absolute ``http``／``https``, host present, no userinfo／query／
    fragment. Path is allowed. The return value always ends with ``/``.

    Raises:
        MaatlogBuildError: with code ``maatlog.feed.baseurl-required`` when invalid
            or missing. Userinfo is redacted from the diagnostic ``value`` field.
    """
    if not isinstance(url, str) or not url.strip():
        raise _baseurl_error(url if isinstance(url, str) else url)

    value = url.strip()
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise _baseurl_error(value) from None

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or any(character.isspace() for character in value)
    ):
        raise _baseurl_error(value)

    path = parsed.path or "/"
    if not path.endswith("/"):
        path = f"{path}/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def absolute_page_url(baseurl: str, builder_uri: str) -> str:
    """Join *baseurl* with a Builder target URI using RFC URL joining.

    *baseurl* should already be validated／normalized (trailing slash). Trailing
    form and percent-encoding of *builder_uri* are preserved by ``urljoin``.
    OS path joins are never used.
    """
    base = baseurl if baseurl.endswith("/") else f"{baseurl}/"
    return urljoin(base, builder_uri)


def absolutize_url(url: str, page_url: str) -> str:
    """Absolutize a single ``href``／``src`` value against *page_url*.

    Fragment-only and relative URLs are resolved. ``mailto``／``tel``／``data``
    and existing absolute ``http``／``https`` URLs are left unchanged.
    """
    if not url:
        return url
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url

    scheme = parsed.scheme.lower()
    if scheme in _PASSTHROUGH_SCHEMES:
        return url
    if scheme in {"http", "https"}:
        return url
    if scheme:
        # Unknown schemes (javascript:, etc.): leave unchanged.
        return url
    return urljoin(page_url, url)


def absolutize_fragment_urls(html: str, page_url: str) -> str:
    """Rewrite relative ``href``／``src`` attributes in an HTML fragment.

    Only element attributes are rewritten via an HTML parser; the rest of the
    fragment (text, comments, other attributes) is preserved without string
    replacement over the whole document.
    """
    parser = _AbsolutizingParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.result()


def redact_url(url: str) -> str:
    """Return *url* with userinfo redacted for diagnostic output.

    Strips credentials from ``netloc`` without reading ``.port`` (or other
    properties that validate the port), so invalid ports still redact safely.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    netloc = parsed.netloc
    if "@" not in netloc:
        return url
    # Keep host:port (or host only); drop userinfo. Avoid .port/.hostname —
    # urlsplit raises ValueError for out-of-range ports when those are read.
    netloc = netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _baseurl_error(url: object) -> MaatlogBuildError:
    if isinstance(url, str):
        display = redact_url(url) if url else ""
    else:
        display = repr(url)
    return MaatlogBuildError(
        [
            Diagnostic(
                code=BASEURL_REQUIRED,
                message="html_baseurl is required for feed generation",
                field="html_baseurl",
                value=display,
                expected=_BASEURL_EXPECTED,
            )
        ]
    )


class _AbsolutizingParser(HTMLParser):
    """Re-serialize HTML while rewriting ``href``／``src`` attribute values."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self._page_url = page_url
        self._parts: list[str] = []

    def result(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._parts.append(self._format_start(tag, attrs, self_closing=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._parts.append(self._format_start(tag, attrs, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._parts.append(f"<?{data}>")

    def _format_start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> str:
        pieces = [f"<{tag}"]
        for name, value in attrs:
            if value is None:
                pieces.append(f" {name}")
                continue
            if name in _HREF_SRC:
                value = absolutize_url(value, self._page_url)
            pieces.append(f' {name}="{_escape_attr(value)}"')
        if self_closing:
            pieces.append(" />")
        else:
            pieces.append(">")
        return "".join(pieces)


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

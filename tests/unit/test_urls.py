"""Unit coverage for MaatLog base URL validation and URL model helpers."""

from __future__ import annotations

import pytest

from maatlog.errors import MaatlogBuildError
from maatlog.urls import (
    absolute_page_url,
    absolutize_fragment_urls,
    absolutize_url,
    post_urls,
    redact_url,
    validate_baseurl,
)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "/docs",
        "ftp://example.com",
        "https://u:p@example.com",
        "https://example.com/#x",
        "https://example.com/?q=1",
        "https://example.com#frag",
        "not-a-url",
        "http://",
        None,
    ],
)
def test_invalid_feed_baseurl(url: str | None) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.feed.baseurl-required"):
        validate_baseurl(url)


def test_invalid_baseurl_redacts_userinfo_in_diagnostic() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        validate_baseurl("https://secret:token@example.com/blog")

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.feed.baseurl-required"
    assert diagnostic.value is not None
    assert "secret" not in diagnostic.value
    assert "token" not in diagnostic.value
    assert "example.com" in diagnostic.value


def test_invalid_baseurl_redacts_userinfo_with_invalid_port() -> None:
    """Userinfo + out-of-range port must still yield MaatlogBuildError, not ValueError."""
    with pytest.raises(MaatlogBuildError) as error:
        validate_baseurl("https://secret:token@example.com:99999/")

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.feed.baseurl-required"
    assert diagnostic.value is not None
    assert "secret" not in diagnostic.value
    assert "token" not in diagnostic.value
    assert "example.com" in diagnostic.value
    assert "99999" in diagnostic.value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com", "https://example.com/"),
        ("https://example.com/", "https://example.com/"),
        ("https://example.com/docs", "https://example.com/docs/"),
        ("https://example.com/docs/", "https://example.com/docs/"),
        ("http://example.com:8080/blog", "http://example.com:8080/blog/"),
    ],
)
def test_validate_baseurl_normalizes_trailing_slash(raw: str, expected: str) -> None:
    assert validate_baseurl(raw) == expected


def test_post_url_roles() -> None:
    urls = post_urls(
        page_url="https://example.com/blog/post/",
        canonical=None,
        external="https://publisher.example/article",
    )
    assert urls.page_url == "https://example.com/blog/post/"
    assert urls.canonical_url == "https://example.com/blog/post/"
    assert urls.external_url == "https://publisher.example/article"
    assert urls.primary_url == "https://publisher.example/article"


def test_post_url_roles_prefer_explicit_canonical() -> None:
    urls = post_urls(
        page_url="https://example.com/blog/post/",
        canonical="https://example.com/canonical/",
        external=None,
    )
    assert urls.canonical_url == "https://example.com/canonical/"
    assert urls.external_url is None
    assert urls.primary_url == "https://example.com/blog/post/"


def test_absolute_page_url_joins_with_urllib_not_os_path() -> None:
    base = validate_baseurl("https://example.com/blog")
    assert absolute_page_url(base, "posts/hello.html") == "https://example.com/blog/posts/hello.html"
    assert absolute_page_url(base, "posts/hello/") == "https://example.com/blog/posts/hello/"
    # Percent-encoding in builder URI is preserved.
    assert absolute_page_url(base, "posts/caf%C3%A9.html") == "https://example.com/blog/posts/caf%C3%A9.html"


def test_absolute_page_url_accepts_base_without_trailing_slash() -> None:
    assert absolute_page_url("https://example.com", "post.html") == "https://example.com/post.html"


@pytest.mark.parametrize(
    ("url", "page", "expected"),
    [
        ("#section", "https://example.com/blog/post/", "https://example.com/blog/post/#section"),
        (
            "images/cover.png",
            "https://example.com/blog/post/",
            "https://example.com/blog/post/images/cover.png",
        ),
        (
            "../other.html",
            "https://example.com/blog/post/",
            "https://example.com/blog/other.html",
        ),
        (
            "https://cdn.example/a.png",
            "https://example.com/blog/post/",
            "https://cdn.example/a.png",
        ),
        (
            "mailto:author@example.com",
            "https://example.com/blog/post/",
            "mailto:author@example.com",
        ),
        ("tel:+1-555-0100", "https://example.com/blog/post/", "tel:+1-555-0100"),
        (
            "data:text/plain;base64,SGVsbG8=",
            "https://example.com/blog/post/",
            "data:text/plain;base64,SGVsbG8=",
        ),
    ],
)
def test_absolutize_url_roles(url: str, page: str, expected: str) -> None:
    assert absolutize_url(url, page) == expected


def test_absolutize_fragment_urls_rewrites_href_and_src_only() -> None:
    page = "https://example.com/blog/post/"
    html = (
        '<p>See <a href="related.html">related</a> and '
        '<img src="images/pic.png" alt="x"> '
        '<a href="mailto:a@b.com">mail</a> '
        '<a href="#notes">notes</a> '
        '<a href="https://external.example/">ext</a> '
        '<span data-url="leave-me">x</span></p>'
    )
    result = absolutize_fragment_urls(html, page)

    assert 'href="https://example.com/blog/post/related.html"' in result
    assert 'src="https://example.com/blog/post/images/pic.png"' in result
    assert 'href="mailto:a@b.com"' in result
    assert 'href="https://example.com/blog/post/#notes"' in result
    assert 'href="https://external.example/"' in result
    assert 'data-url="leave-me"' in result
    # Does not string-replace bare relative paths outside attributes.
    assert "leave-me" in result


def test_absolutize_fragment_urls_preserves_text_and_comments() -> None:
    page = "https://example.com/p/"
    result = absolutize_fragment_urls(
        '<!-- href=relative.html --> <p>keep <a href="x.html">link</a> text</p>',
        page,
    )
    assert "<!-- href=relative.html -->" in result
    assert result.endswith(" text</p>") or " text</p>" in result
    assert 'href="https://example.com/p/x.html"' in result
    assert "href=relative.html" in result  # comment body not rewritten


def test_redact_url_strips_userinfo() -> None:
    assert redact_url("https://user:pass@example.com/path") == "https://example.com/path"
    assert redact_url("https://example.com/path") == "https://example.com/path"
    assert redact_url("https://secret:token@example.com:99999/") == "https://example.com:99999/"

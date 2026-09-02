"""Unit tests for HTML metadata helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from maatlog.html_metadata import format_post_date, strip_leading_document_title


@pytest.mark.parametrize(
    ("body_html", "document_title", "expected"),
    [
        (
            '<section id="hello"><h1>Title<a class="headerlink" href="#hello">¶</a></h1><p>Body</p></section>',
            "Title",
            '<section id="hello"><p>Body</p></section>',
        ),
        (
            '<section id="numbered"><h1><span class="toc section-number">1. </span>Title'
            '<a class="headerlink" href="#numbered">¶</a></h1><p>Body</p></section>',
            "Title",
            '<section id="numbered"><p>Body</p></section>',
        ),
        (
            '<section><h1><span class="eyebrow">Draft </span>Title</h1><p>Body</p></section>',
            "Title",
            '<section><h1><span class="eyebrow">Draft </span>Title</h1><p>Body</p></section>',
        ),
        ("<p>No heading here.</p>", "Title", "<p>No heading here.</p>"),
    ],
)
def test_strip_leading_document_title_removes_only_matching_h1(
    body_html: str, document_title: str, expected: str
) -> None:
    assert strip_leading_document_title(body_html, document_title=document_title) == expected


def test_strip_leading_document_title_leaves_later_headings() -> None:
    body_html = "<h1>Title</h1><h1>Another</h1><p>Body</p>"
    assert strip_leading_document_title(body_html, document_title="Title") == "<h1>Another</h1><p>Body</p>"


def test_strip_leading_document_title_preserves_injected_h1_before_title() -> None:
    body_html = "<h1>Injected banner</h1><section><h1>Real Post Title</h1><p>x</p></section>"
    assert (
        strip_leading_document_title(body_html, document_title="Real Post Title")
        == "<h1>Injected banner</h1><section><p>x</p></section>"
    )


def test_strip_leading_document_title_matches_html_entities_in_h1() -> None:
    body_html = "<section><h1>Tips &amp; Tricks</h1><p>Body</p></section>"
    assert strip_leading_document_title(body_html, document_title="Tips & Tricks") == "<section><p>Body</p></section>"


def test_format_post_date_uses_site_timezone() -> None:
    published_at = datetime(2025, 6, 28, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert format_post_date(published_at, ZoneInfo("Asia/Tokyo")) == "2025年6月28日"


def test_format_post_date_shifts_calendar_day_across_timezones() -> None:
    published_at = datetime(2025, 6, 28, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert format_post_date(published_at, ZoneInfo("UTC")) == "2025年6月27日"

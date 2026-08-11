from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import pytest

from maatlog.model import Post, PublicationStatus
from maatlog.views import (
    MaatlogTemplateContext,
    as_template_mapping,
    build_post_context,
    empty_context,
    post_view,
)

PostFactory = Callable[..., Post]


@pytest.fixture
def post() -> PostFactory:
    def factory(**overrides: Any) -> Post:
        values: dict[str, Any] = {
            "docname": "blog/hello",
            "source_path": "blog/hello.md",
            "title": "Hello",
            "slug": "hello",
            "published_at": datetime(2026, 8, 1, tzinfo=UTC),
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


def test_empty_context_has_all_public_keys() -> None:
    context = empty_context()
    assert tuple(asdict(context)) == (
        "api_version",
        "page_kind",
        "post",
        "posts",
        "archive",
        "pagination",
        "navigation",
        "feeds",
        "taxonomies",
    )


def test_empty_context_defaults() -> None:
    context = empty_context()
    assert context.api_version == "1.0"
    assert context.page_kind == "normal"
    assert context.post is None
    assert context.posts == ()
    assert context.archive is None
    assert context.pagination is None
    assert context.navigation.newer_post is None
    assert context.navigation.older_post is None
    assert context.feeds == ()
    assert context.taxonomies.tags == ()
    assert context.taxonomies.categories == ()
    assert context.taxonomies.authors == ()
    assert context.taxonomies.months == ()


def test_external_post_does_not_expose_body_html(post: PostFactory) -> None:
    view = post_view(
        post(external_url="https://outside.example/x", excerpt="Summary"),
        body_html="secret",
    )
    assert view.body_html is None
    assert view.excerpt == "Summary"
    assert view.external_url == "https://outside.example/x"


def test_internal_post_keeps_body_html(post: PostFactory) -> None:
    view = post_view(post(), body_html="<p>Body</p>")
    assert view.body_html == "<p>Body</p>"


def test_build_post_context_sets_page_kind(post: PostFactory) -> None:
    context = build_post_context(post(), body_html="<p>x</p>", page_url="hello.html")
    assert context.page_kind == "post"
    assert context.post is not None
    assert context.post.page_url == "hello.html"
    assert context.post.body_html == "<p>x</p>"
    mapping = as_template_mapping(context)
    assert mapping["api_version"] == "1.0"
    assert mapping["page_kind"] == "post"
    assert mapping["post"]["body_html"] == "<p>x</p>"


def test_as_template_mapping_preserves_public_key_order() -> None:
    mapping = as_template_mapping(MaatlogTemplateContext())
    assert tuple(mapping) == (
        "api_version",
        "page_kind",
        "post",
        "posts",
        "archive",
        "pagination",
        "navigation",
        "feeds",
        "taxonomies",
    )

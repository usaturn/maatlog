from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from maatlog.errors import Diagnostic, MaatlogBuildError
from maatlog.featured import select_featured_posts
from maatlog.model import Post, PublicationStatus
from maatlog.views import FEATURED_LIMIT

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


def _published(post: PostFactory, *slugs: str) -> tuple[Post, ...]:
    """Build published posts in the given (newest-first) order."""
    count = len(slugs)
    return tuple(
        post(
            docname=slug,
            slug=slug,
            title=slug,
            published_at=datetime(2026, 8, count - index, tzinfo=UTC),
        )
        for index, slug in enumerate(slugs)
    )


def _select(
    configured: tuple[str, ...] | None,
    published: Sequence[Post],
    *extra: Post,
    home_docname: str | None = None,
) -> tuple[Post, ...] | None:
    # Insert extras and oldest-first so fill must walk `published`, not mapping order.
    posts_by_docname = {item.docname: item for item in (*extra, *reversed(tuple(published)))}
    return select_featured_posts(
        configured,
        posts_by_docname=posts_by_docname,
        published=published,
        home_docname=home_docname,
    )


def _slugs(posts: Sequence[Post]) -> tuple[str, ...]:
    return tuple(item.slug for item in posts)


def _assert_featured_diagnostic(
    diagnostic: Diagnostic,
    *,
    code: str,
    slug: str,
    message: str,
    expected: str,
) -> None:
    assert diagnostic.code == code
    assert diagnostic.message == message
    assert diagnostic.field == "maatlog_featured_posts"
    assert diagnostic.value == repr(slug)
    assert diagnostic.expected == expected


@pytest.mark.parametrize("configured", [None, ()])
def test_none_and_empty_configured_return_none(post: PostFactory, configured: tuple[str, ...] | None) -> None:
    published = _published(post, "e", "d", "c", "b", "a")
    assert _select(configured, published) is None


@pytest.mark.parametrize("count", [0, 1, 2])
def test_unspecified_with_few_published_posts_returns_none(post: PostFactory, count: int) -> None:
    slugs = ("c", "b", "a")[:count]
    published = _published(post, *slugs) if slugs else ()
    assert _select(None, published) is None
    assert _select((), published) is None


def test_one_specified_post_is_filled_from_newest_published(post: PostFactory) -> None:
    published = _published(post, "e", "d", "c", "b", "a")
    result = _select(("a",), published)
    assert result is not None
    assert _slugs(result) == ("a", "e", "d")
    assert len(result) == FEATURED_LIMIT


def test_three_specified_posts_keep_configured_order_without_fill(post: PostFactory) -> None:
    published = _published(post, "e", "d", "c", "b", "a")
    result = _select(("c", "a", "b"), published)
    assert result is not None
    assert _slugs(result) == ("c", "a", "b")


def test_four_specified_posts_return_only_the_first_three(post: PostFactory) -> None:
    published = _published(post, "e", "d", "c", "b", "a")
    result = _select(("a", "b", "c", "d"), published)
    assert result is not None
    assert _slugs(result) == ("a", "b", "c")
    assert "d" not in _slugs(result)


def test_one_specified_among_two_published_fills_the_remainder(post: PostFactory) -> None:
    published = _published(post, "new", "old")
    result = _select(("old",), published)
    assert result is not None
    assert _slugs(result) == ("old", "new")


def test_duplicate_slug_raises(post: PostFactory) -> None:
    published = _published(post, "lead")
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("lead", "lead"), published)
    _assert_featured_diagnostic(
        caught.value.diagnostics[0],
        code="maatlog.featured.duplicate",
        slug="lead",
        message="Featured post 'lead' is duplicated",
        expected="a unique slug",
    )


def test_unknown_slug_raises(post: PostFactory) -> None:
    published = _published(post, "lead")
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("ghost",), published)
    _assert_featured_diagnostic(
        caught.value.diagnostics[0],
        code="maatlog.featured.unknown",
        slug="ghost",
        message="Featured post 'ghost' does not exist",
        expected="the slug of an existing post",
    )


@pytest.mark.parametrize(
    "status",
    [PublicationStatus.DRAFT, PublicationStatus.SCHEDULED, PublicationStatus.EXPIRED],
)
def test_unpublished_explicit_slug_raises(post: PostFactory, status: PublicationStatus) -> None:
    hidden = post(docname="hidden", slug="hidden", title="hidden", status=status)
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("hidden",), (), hidden)
    _assert_featured_diagnostic(
        caught.value.diagnostics[0],
        code="maatlog.featured.unpublished",
        slug="hidden",
        message="Featured post 'hidden' is not published",
        expected="the slug of a published post",
    )


def test_home_docname_match_raises_self(post: PostFactory) -> None:
    home = post(docname="index", slug="welcome", title="Welcome")
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("welcome",), (home,), home_docname="index")
    _assert_featured_diagnostic(
        caught.value.diagnostics[0],
        code="maatlog.featured.self",
        slug="welcome",
        message="Featured post 'welcome' is the home document",
        expected="a post other than the home document",
    )


def test_fourth_unknown_slug_is_still_diagnosed(post: PostFactory) -> None:
    published = _published(post, "c", "b", "a")
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("a", "b", "c", "ghost"), published)
    _assert_featured_diagnostic(
        caught.value.diagnostics[0],
        code="maatlog.featured.unknown",
        slug="ghost",
        message="Featured post 'ghost' does not exist",
        expected="the slug of an existing post",
    )


def test_collects_every_slug_problem(post: PostFactory) -> None:
    lead = _published(post, "lead")[0]
    draft = post(docname="draft", slug="draft", title="draft", status=PublicationStatus.DRAFT)
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("ghost", "draft", "lead", "lead"), (lead,), draft)
    by_code = {item.code: item for item in caught.value.diagnostics}
    _assert_featured_diagnostic(
        by_code["maatlog.featured.unknown"],
        code="maatlog.featured.unknown",
        slug="ghost",
        message="Featured post 'ghost' does not exist",
        expected="the slug of an existing post",
    )
    _assert_featured_diagnostic(
        by_code["maatlog.featured.unpublished"],
        code="maatlog.featured.unpublished",
        slug="draft",
        message="Featured post 'draft' is not published",
        expected="the slug of a published post",
    )
    _assert_featured_diagnostic(
        by_code["maatlog.featured.duplicate"],
        code="maatlog.featured.duplicate",
        slug="lead",
        message="Featured post 'lead' is duplicated",
        expected="a unique slug",
    )


def test_unpublished_home_emits_unpublished_and_self(post: PostFactory) -> None:
    home = post(docname="index", slug="welcome", title="Welcome", status=PublicationStatus.DRAFT)
    with pytest.raises(MaatlogBuildError) as caught:
        _select(("welcome",), (), home, home_docname="index")
    codes = {item.code for item in caught.value.diagnostics}
    assert codes == {"maatlog.featured.unpublished", "maatlog.featured.self"}


def test_home_document_is_excluded_from_fill(post: PostFactory) -> None:
    published = _published(post, "home", "b", "c", "d")
    result = _select(("d",), published, home_docname="home")
    assert result is not None
    assert _slugs(result) == ("d", "b", "c")
    assert "home" not in _slugs(result)


def test_home_slug_is_selectable_when_home_docname_is_none(post: PostFactory) -> None:
    published = _published(post, "welcome", "b", "c")
    result = _select(("welcome",), published, home_docname=None)
    assert result is not None
    assert _slugs(result) == ("welcome", "b", "c")

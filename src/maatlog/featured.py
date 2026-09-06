from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import Diagnostic, MaatlogBuildError
from .model import Post, PublicationStatus
from .views import FEATURED_LIMIT

UNKNOWN_CODE = "maatlog.featured.unknown"
UNPUBLISHED_CODE = "maatlog.featured.unpublished"
DUPLICATE_CODE = "maatlog.featured.duplicate"
SELF_CODE = "maatlog.featured.self"

_FIELD = "maatlog_featured_posts"


def select_featured_posts(
    configured: tuple[str, ...] | None,
    *,
    posts_by_docname: Mapping[str, Post],
    published: Sequence[Post],
    home_docname: str | None,
) -> tuple[Post, ...] | None:
    """Return displayed featured posts (at most FEATURED_LIMIT), or None for the View default."""
    if not configured:
        return None

    posts_by_slug = {post.slug: post for post in posts_by_docname.values()}
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    for slug in configured:
        if slug in seen:
            diagnostics.append(
                _slug_diagnostic(
                    DUPLICATE_CODE,
                    slug,
                    f"Featured post {slug!r} is duplicated",
                    "a unique slug",
                )
            )
            continue
        seen.add(slug)
        post = posts_by_slug.get(slug)
        if post is None:
            diagnostics.append(
                _slug_diagnostic(
                    UNKNOWN_CODE,
                    slug,
                    f"Featured post {slug!r} does not exist",
                    "the slug of an existing post",
                )
            )
            continue
        if post.status is not PublicationStatus.PUBLISHED:
            diagnostics.append(
                _slug_diagnostic(
                    UNPUBLISHED_CODE,
                    slug,
                    f"Featured post {slug!r} is not published",
                    "the slug of a published post",
                )
            )
        if home_docname is not None and post.docname == home_docname:
            diagnostics.append(
                _slug_diagnostic(
                    SELF_CODE,
                    slug,
                    f"Featured post {slug!r} is the home document",
                    "a post other than the home document",
                )
            )

    if diagnostics:
        raise MaatlogBuildError(diagnostics)

    selected: list[Post] = []
    for slug in configured:
        if len(selected) >= FEATURED_LIMIT:
            break
        selected.append(posts_by_slug[slug])

    if len(selected) >= FEATURED_LIMIT:
        return tuple(selected)

    chosen_slugs = {post.slug for post in selected}
    for post in published:
        if post.docname == home_docname or post.slug in chosen_slugs:
            continue
        selected.append(post)
        chosen_slugs.add(post.slug)
        if len(selected) >= FEATURED_LIMIT:
            break
    return tuple(selected)


def _slug_diagnostic(code: str, slug: str, message: str, expected: str) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        field=_FIELD,
        value=repr(slug),
        expected=expected,
    )

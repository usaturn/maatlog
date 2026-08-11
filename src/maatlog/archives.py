"""Immutable archive page projection: filter, pagination, and docnames."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import ceil
from zoneinfo import ZoneInfo

from .config import TaxonomyAxis
from .errors import Diagnostic, MaatlogBuildError
from .model import Post
from .references import archive_docname
from .taxonomy import DomainIndex


@dataclass(frozen=True, slots=True)
class PostFilter:
    """Filter for published posts. Empty axis means no constraint.

    Within one axis, multiple IDs are OR. Across axes and month, constraints AND.
    """

    tags: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    month: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveKey:
    """Identity of an archive listing (all posts, or one taxonomy/month value)."""

    axis: TaxonomyAxis | None
    value: str | None
    label: str


@dataclass(frozen=True, slots=True)
class PageSlice:
    """One page of a filtered post sequence (1-origin page numbers)."""

    number: int
    total_pages: int
    posts: tuple[Post, ...]

    @property
    def docname_suffix(self) -> str:
        return "" if self.number == 1 else f"/page/{self.number}"


@dataclass(frozen=True, slots=True)
class ArchivePage:
    """One generated archive page ready for collection / rendering."""

    key: ArchiveKey
    docname: str
    number: int
    total_pages: int
    posts: tuple[Post, ...]
    total_posts: int


def filter_posts(
    posts: Sequence[Post],
    post_filter: PostFilter,
    *,
    timezone: ZoneInfo,
) -> tuple[Post, ...]:
    """Keep posts matching *post_filter*, preserving input order.

    Same-axis IDs are OR; different axes and month are AND. An empty axis
    tuple (or ``month is None``) imposes no constraint on that dimension.
    """
    return tuple(post for post in posts if _matches(post, post_filter, timezone=timezone))


def paginate(posts: Sequence[Post], page_size: int) -> tuple[PageSlice, ...]:
    """Split *posts* into 1-origin pages of *page_size*.

    Empty input yields a single empty page 1. Page 1 has no ``/page/1`` suffix.
    """
    if page_size < 1:
        msg = f"page_size must be >= 1, got {page_size}"
        raise ValueError(msg)

    if not posts:
        return (PageSlice(number=1, total_pages=1, posts=()),)

    total_pages = ceil(len(posts) / page_size)
    return tuple(
        PageSlice(
            number=number,
            total_pages=total_pages,
            posts=tuple(posts[(number - 1) * page_size : number * page_size]),
        )
        for number in range(1, total_pages + 1)
    )


def project_archives(
    index: DomainIndex,
    *,
    root: str,
    page_size: int,
    timezone: ZoneInfo,
) -> tuple[ArchivePage, ...]:
    """Project all archive pages from a published domain index.

    The all-posts archive is always produced (even with zero posts). Taxonomy
    and month archives are produced only when they have at least one post.
    """
    pages: list[ArchivePage] = []
    pages.extend(
        _pages_for_key(
            posts=index.published,
            key=ArchiveKey(axis=None, value=None, label="Posts"),
            root=root,
            page_size=page_size,
        )
    )

    for axis in (TaxonomyAxis.TAG, TaxonomyAxis.CATEGORY, TaxonomyAxis.AUTHOR, TaxonomyAxis.MONTH):
        axis_members = index.members.get(axis, {})
        axis_labels = index.labels.get(axis, {})
        for value, _slugs in axis_members.items():
            if axis is TaxonomyAxis.MONTH:
                post_filter = PostFilter(month=value)
            elif axis is TaxonomyAxis.TAG:
                post_filter = PostFilter(tags=(value,))
            elif axis is TaxonomyAxis.CATEGORY:
                post_filter = PostFilter(categories=(value,))
            else:
                post_filter = PostFilter(authors=(value,))

            filtered = filter_posts(index.published, post_filter, timezone=timezone)
            if not filtered:
                continue
            label = axis_labels.get(value, value)
            pages.extend(
                _pages_for_key(
                    posts=filtered,
                    key=ArchiveKey(axis=axis, value=value, label=label),
                    root=root,
                    page_size=page_size,
                )
            )

    return tuple(pages)


def _pages_for_key(
    *,
    posts: Sequence[Post],
    key: ArchiveKey,
    root: str,
    page_size: int,
) -> list[ArchivePage]:
    slices = paginate(posts, page_size)
    total_posts = len(posts)
    return [
        ArchivePage(
            key=key,
            docname=archive_docname(root, key.axis, key.value, page=slice_.number),
            number=slice_.number,
            total_pages=slice_.total_pages,
            posts=slice_.posts,
            total_posts=total_posts,
        )
        for slice_ in slices
    ]


def check_generated_docnames(
    generated: Sequence[str],
    *,
    known_docnames: Collection[str],
) -> None:
    """Raise when projected archive docnames collide with sources or each other.

    Collisions with Sphinx source / known docnames, or internal duplicates among
    MaatLog pages, raise :class:`MaatlogBuildError` with
    ``maatlog.generated-docname.conflict`` before any archive page is yielded or
    owned outputs are committed.
    """
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    known = set(known_docnames)
    for docname in generated:
        if docname in seen or docname in known:
            diagnostics.append(
                Diagnostic(
                    code="maatlog.generated-docname.conflict",
                    message=f"Generated archive docname conflicts with an existing document: {docname}",
                    field="docname",
                    value=docname,
                    expected="unused relative docname",
                )
            )
        seen.add(docname)
    if diagnostics:
        raise MaatlogBuildError(diagnostics)


def _matches(post: Post, post_filter: PostFilter, *, timezone: ZoneInfo) -> bool:
    if post_filter.tags and not any(tag in post.tags for tag in post_filter.tags):
        return False
    if post_filter.categories and not any(cat in post.categories for cat in post_filter.categories):
        return False
    if post_filter.authors and not any(author in post.authors for author in post_filter.authors):
        return False
    if post_filter.month is not None:
        if post.published_at is None:
            return False
        month = post.published_at.astimezone(timezone).strftime("%Y-%m")
        if month != post_filter.month:
            return False
    return True

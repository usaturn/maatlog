"""Post neighbors and sidebar taxonomy navigation from published snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from weakref import WeakKeyDictionary

from sphinx.builders import Builder

from .config import TaxonomyAxis
from .model import Post
from .references import archive_docname
from .taxonomy import DomainIndex
from .views import (
    PostTaxonomiesView,
    TaxonomyItemView,
    TaxonomyLinkView,
    TaxonomyNavigationView,
    relative_page_url_for,
)


def neighbors(published: Sequence[Post], slug: str) -> tuple[Post | None, Post | None]:
    """Return ``(newer, older)`` for *slug* within the published sequence.

    *published* must already be the site-wide published order (newest first).
    Unpublished posts are never present in that sequence, so they are skipped.
    Boundary posts yield ``None`` on the missing side. Unknown *slug* yields
    ``(None, None)``.
    """
    index_by_slug = {post.slug: offset for offset, post in enumerate(published)}
    offset = index_by_slug.get(slug)
    if offset is None:
        return None, None
    newer = published[offset - 1] if offset > 0 else None
    older = published[offset + 1] if offset + 1 < len(published) else None
    return newer, older


@dataclass(frozen=True, slots=True)
class TaxonomyRow:
    """One taxonomy value, independent of which page links to it."""

    id: str
    label: str
    count: int
    target_docname: str


# Page-independent rows, memoised per builder. Keyed by the builder because a
# DomainIndex is a pydantic model holding dicts and is therefore unhashable.
# The entry is discarded when the index or archive root changes, and the weak
# key lets it go when the builder does. Parallel builds fork, so each worker
# process keeps its own cache.
type _AxisCacheKey = tuple[TaxonomyAxis, bool, bool]
_ROW_CACHE: WeakKeyDictionary[Builder, tuple[DomainIndex, str, dict[_AxisCacheKey, tuple[TaxonomyRow, ...]]]] = (
    WeakKeyDictionary()
)


def _cached_axis_rows(
    index: DomainIndex,
    *,
    builder: Builder,
    axis: TaxonomyAxis,
    root: str,
    reverse: bool,
    sort_by_label: bool,
) -> tuple[TaxonomyRow, ...]:
    entry = _ROW_CACHE.get(builder)
    if entry is None or entry[0] is not index or entry[1] != root:
        cached_by_axis: dict[_AxisCacheKey, tuple[TaxonomyRow, ...]] = {}
        entry = (index, root, cached_by_axis)
        _ROW_CACHE[builder] = entry
    # The ordering parameters belong in the key: the same axis may be asked for
    # in a different order, and a key without them would latch the first order.
    key: _AxisCacheKey = (axis, reverse, sort_by_label)
    cached = entry[2].get(key)
    if cached is None:
        cached = _axis_rows(index, axis=axis, root=root, reverse=reverse, sort_by_label=sort_by_label)
        entry[2][key] = cached
    return cached


def taxonomy_navigation(
    index: DomainIndex,
    *,
    builder: Builder,
    from_docname: str,
    root: str,
) -> TaxonomyNavigationView:
    """Build sidebar taxonomy links and counts from published membership only.

    Tag, category, and author items are ordered by label Unicode code points.
    Month items are ordered by ``YYYY-MM`` descending. Zero-count entries are
    never present in :class:`DomainIndex` membership.
    """
    return TaxonomyNavigationView(
        tags=_axis_items(
            index,
            axis=TaxonomyAxis.TAG,
            builder=builder,
            from_docname=from_docname,
            root=root,
            reverse=False,
            sort_by_label=True,
        ),
        categories=_axis_items(
            index,
            axis=TaxonomyAxis.CATEGORY,
            builder=builder,
            from_docname=from_docname,
            root=root,
            reverse=False,
            sort_by_label=True,
        ),
        authors=_axis_items(
            index,
            axis=TaxonomyAxis.AUTHOR,
            builder=builder,
            from_docname=from_docname,
            root=root,
            reverse=False,
            sort_by_label=True,
        ),
        months=_axis_items(
            index,
            axis=TaxonomyAxis.MONTH,
            builder=builder,
            from_docname=from_docname,
            root=root,
            reverse=True,
            sort_by_label=False,
        ),
    )


def _axis_rows(
    index: DomainIndex,
    *,
    axis: TaxonomyAxis,
    root: str,
    reverse: bool,
    sort_by_label: bool,
) -> tuple[TaxonomyRow, ...]:
    """Collect id / label / count / target docname for one axis.

    Pure: depends only on *index* and *root*, never on the page being rendered.
    Tags, categories and authors are ordered by label; months by ``YYYY-MM``.
    """
    members = index.members.get(axis, {})
    labels = index.labels.get(axis, {})
    rows = [
        TaxonomyRow(
            id=taxonomy_id,
            label=labels.get(taxonomy_id, taxonomy_id),
            count=len(slugs),
            target_docname=archive_docname(root, axis, taxonomy_id, page=1),
        )
        for taxonomy_id, slugs in members.items()
    ]
    rows.sort(key=(lambda row: row.label) if sort_by_label else (lambda row: row.id), reverse=reverse)
    return tuple(rows)


def _is_current_archive(from_docname: str, target_docname: str) -> bool:
    """*from_docname* が *target_docname* のアーカイブ本体かページ送りか。

    ``archive_docname`` は 1 ページ目を接尾辞なし、2 ページ目以降を
    ``{base}/page/{n}`` で返す。接頭辞一致だけで判定すると
    ``blog/tag/alpha`` が ``blog/tag/alphabet`` に誤って一致するため、
    完全一致か ``/page/`` 付きかのどちらかに限定する。
    """
    return from_docname == target_docname or from_docname.startswith(f"{target_docname}/page/")


def _axis_items(
    index: DomainIndex,
    *,
    axis: TaxonomyAxis,
    builder: Builder,
    from_docname: str,
    root: str,
    reverse: bool,
    sort_by_label: bool,
) -> tuple[TaxonomyItemView, ...]:
    rows = _cached_axis_rows(
        index,
        builder=builder,
        axis=axis,
        root=root,
        reverse=reverse,
        sort_by_label=sort_by_label,
    )
    return tuple(
        TaxonomyItemView(
            id=row.id,
            label=row.label,
            count=row.count,
            url=relative_page_url_for(builder, from_docname, row.target_docname),
            is_current=_is_current_archive(from_docname, row.target_docname),
        )
        for row in rows
    )


@dataclass(slots=True)
class PostTaxonomyLinker:
    """Resolve a post's taxonomy IDs into labelled archive links.

    Not frozen: a per-page URL cache lives here. One instance is built per
    rendered page, so the cache lifetime is the page.
    Only taxonomy IDs present in *members* (published membership) get URLs;
    others render as plain spans with ``url=""``.
    """

    builder: Builder
    from_docname: str
    root: str
    labels: Mapping[TaxonomyAxis, Mapping[str, str]]
    members: Mapping[TaxonomyAxis, Mapping[str, tuple[str, ...]]]
    _cache: dict[tuple[TaxonomyAxis, str], TaxonomyLinkView] = field(
        default_factory=dict[tuple[TaxonomyAxis, str], TaxonomyLinkView]
    )

    def for_post(self, post: Post) -> PostTaxonomiesView:
        return PostTaxonomiesView(
            tags=self._links(TaxonomyAxis.TAG, post.tags),
            categories=self._links(TaxonomyAxis.CATEGORY, post.categories),
            authors=self._links(TaxonomyAxis.AUTHOR, post.authors),
        )

    def for_authors(self, ids: Sequence[str]) -> tuple[TaxonomyLinkView, ...]:
        """Resolve author ids into links, keeping the order they were given in.

        The right rail needs display names and profile URLs for authors that do
        not come from a post (the configured default author), so this exposes
        the same per-page resolution and cache ``for_post`` uses.
        """
        return self._links(TaxonomyAxis.AUTHOR, tuple(ids))

    def _links(self, axis: TaxonomyAxis, ids: tuple[str, ...]) -> tuple[TaxonomyLinkView, ...]:
        return tuple(self._link(axis, taxonomy_id) for taxonomy_id in ids)

    def _link(self, axis: TaxonomyAxis, taxonomy_id: str) -> TaxonomyLinkView:
        cached = self._cache.get((axis, taxonomy_id))
        if cached is not None:
            return cached
        labels = self.labels.get(axis, {})
        members = self.members.get(axis, {})
        url = ""
        if taxonomy_id in members:
            url = relative_page_url_for(
                self.builder,
                self.from_docname,
                archive_docname(self.root, axis, taxonomy_id, page=1),
            )
        link = TaxonomyLinkView(
            id=taxonomy_id,
            label=labels.get(taxonomy_id, taxonomy_id),
            url=url,
        )
        self._cache[(axis, taxonomy_id)] = link
        return link


def post_taxonomy_linker(
    index: DomainIndex | None,
    *,
    builder: Builder,
    from_docname: str,
    root: str,
) -> PostTaxonomyLinker:
    """Build a :class:`PostTaxonomyLinker` for one rendered page."""
    return PostTaxonomyLinker(
        builder=builder,
        from_docname=from_docname,
        root=root,
        labels=index.labels if index is not None else {},
        members=index.members if index is not None else {},
    )

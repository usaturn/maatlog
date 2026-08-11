"""Post neighbors and sidebar taxonomy navigation from published snapshots."""

from __future__ import annotations

from collections.abc import Sequence

from sphinx.builders import Builder

from .config import TaxonomyAxis
from .model import Post
from .references import archive_docname
from .taxonomy import DomainIndex
from .views import TaxonomyItemView, TaxonomyNavigationView, relative_page_url_for


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
    members = index.members.get(axis, {})
    labels = index.labels.get(axis, {})
    rows: list[tuple[str, str, int]] = []
    for taxonomy_id, slugs in members.items():
        label = labels.get(taxonomy_id, taxonomy_id)
        rows.append((taxonomy_id, label, len(slugs)))

    if sort_by_label:
        rows.sort(key=lambda row: row[1], reverse=reverse)
    else:
        rows.sort(key=lambda row: row[0], reverse=reverse)

    return tuple(
        TaxonomyItemView(
            id=taxonomy_id,
            label=label,
            count=count,
            url=relative_page_url_for(
                builder,
                from_docname,
                archive_docname(root, axis, taxonomy_id, page=1),
            ),
        )
        for taxonomy_id, label, count in rows
    )

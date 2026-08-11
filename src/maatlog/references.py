"""Cross-reference roles, archive docnames, and lookup helpers for MaatLog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sphinx.roles import XRefRole

from .config import TaxonomyAxis
from .model import Post, PublicationStatus
from .taxonomy import DomainIndex

ROLE_TYPES: tuple[str, ...] = ("post", "tag", "category", "author", "month")

_TAXONOMY_ROLES: frozenset[str] = frozenset(axis.value for axis in TaxonomyAxis)


class MaatlogXRefRole(XRefRole):
    """Cross-reference role that warns when the target cannot be resolved."""

    def __init__(self) -> None:
        super().__init__(warn_dangling=True)


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """A resolved MaatLog object reference target."""

    docname: str
    anchor: str
    label: str


def archive_docname(
    root: str,
    axis: TaxonomyAxis | str | None = None,
    key: str | None = None,
    page: int = 1,
) -> str:
    """Return the Sphinx docname for an archive page (Plan 04 URI scheme).

    Page 1 has no ``/page/1`` suffix. Taxonomy pages use ``{root}/{axis}/{key}``.
    The all-posts archive uses ``{root}`` when *axis* and *key* are both ``None``.
    """
    if page < 1:
        msg = f"page must be >= 1, got {page}"
        raise ValueError(msg)

    if axis is None:
        if key is not None:
            msg = "key must be None when axis is None"
            raise ValueError(msg)
        base = root
    else:
        if key is None:
            msg = "key is required when axis is set"
            raise ValueError(msg)
        axis_value = axis.value if isinstance(axis, TaxonomyAxis) else str(axis)
        base = f"{root}/{axis_value}/{key}"

    if page == 1:
        return base
    return f"{base}/page/{page}"


def lookup_reference(
    *,
    typ: str,
    target: str,
    index: DomainIndex | None,
    posts_by_docname: Mapping[str, Post],
    archive_root: str,
) -> ResolvedReference | None:
    """Resolve a MaatLog object by exact type and case-sensitive key.

    Posts resolve for any registered slug (including drafts). Taxonomy and month
    objects resolve only when the index has published members for that key.
    """
    if index is None:
        return None

    if typ == "post":
        docname = index.docname_by_slug.get(target)
        if docname is None:
            return None
        post = posts_by_docname.get(docname)
        if post is None:
            return None
        return ResolvedReference(docname=docname, anchor="", label=post.title)

    if typ not in _TAXONOMY_ROLES:
        return None

    axis = TaxonomyAxis(typ)
    members = index.members.get(axis, {})
    if target not in members:
        return None
    label = index.labels[axis][target]
    docname = archive_docname(archive_root, axis, target, page=1)
    return ResolvedReference(docname=docname, anchor="", label=label)


def iter_inventory_objects(
    *,
    index: DomainIndex | None,
    archive_root: str,
) -> list[tuple[str, str, str, str, str, int]]:
    """Build ``get_objects()`` inventory entries for published posts and taxonomies."""
    if index is None:
        return []

    objects: list[tuple[str, str, str, str, str, int]] = []
    for post in index.published:
        if post.status is not PublicationStatus.PUBLISHED:
            continue
        objects.append((post.slug, post.title, "post", post.docname, "", 1))

    for axis in TaxonomyAxis:
        for key in sorted(index.members.get(axis, {})):
            label = index.labels[axis][key]
            docname = archive_docname(archive_root, axis, key, page=1)
            objects.append((key, label, axis.value, docname, "", 1))

    return objects


def is_html_archive_builder(builder: Any) -> bool:
    """Return True when taxonomy roles should link to archive docnames.

    Full HTML builders (``html`` / ``dirhtml``) only. Partial HTML and
    document-only builders resolve taxonomy roles as inline labels instead.
    """
    from .builders import is_full_html_builder

    return is_full_html_builder(builder)

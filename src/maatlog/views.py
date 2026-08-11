"""Stable, template-facing view models for the MaatLog Theme API 1.0 context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal, Self, cast

from jinja2 import TemplateNotFound
from sphinx.application import Sphinx
from sphinx.builders import Builder
from sphinx.util.osutil import relative_uri

from .archives import ArchivePage
from .model import Post
from .urls import post_urls

PageKind = Literal["normal", "post", "archive"]


@dataclass(frozen=True, slots=True)
class FeedLinkView:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class TaxonomyItemView:
    id: str
    label: str
    count: int
    url: str


@dataclass(frozen=True, slots=True)
class TaxonomyNavigationView:
    tags: tuple[TaxonomyItemView, ...]
    categories: tuple[TaxonomyItemView, ...]
    authors: tuple[TaxonomyItemView, ...]
    months: tuple[TaxonomyItemView, ...]

    @classmethod
    def empty(cls) -> Self:
        return cls((), (), (), ())


@dataclass(frozen=True, slots=True)
class PostCardView:
    title: str
    page_url: str
    published_at: datetime | None
    excerpt: str | None
    image_url: str | None
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    authors: tuple[str, ...]
    external_url: str | None
    slug: str | None = None


@dataclass(frozen=True, slots=True)
class PostView:
    title: str
    slug: str
    docname: str
    page_url: str
    canonical_url: str | None
    external_url: str | None
    published_at: datetime | None
    expires_at: datetime | None
    excerpt: str | None
    image_url: str | None
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    authors: tuple[str, ...]
    body_html: str | None


@dataclass(frozen=True, slots=True)
class ArchiveView:
    kind: str
    id: str | None
    label: str
    docname: str
    page_number: int
    total_posts: int


@dataclass(frozen=True, slots=True)
class PaginationView:
    current: int
    total_pages: int
    previous_url: str | None
    next_url: str | None
    pages: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class NavigationView:
    newer_post: PostCardView | None
    older_post: PostCardView | None


@dataclass(frozen=True, slots=True)
class MaatlogTemplateContext:
    api_version: str = "1.0"
    page_kind: PageKind = "normal"
    post: PostView | None = None
    posts: tuple[PostCardView, ...] = ()
    archive: ArchiveView | None = None
    pagination: PaginationView | None = None
    navigation: NavigationView = NavigationView(None, None)
    feeds: tuple[FeedLinkView, ...] = ()
    taxonomies: TaxonomyNavigationView = TaxonomyNavigationView.empty()


def empty_context() -> MaatlogTemplateContext:
    """Return a fully-keyed normal-page context with empty / None values."""
    return MaatlogTemplateContext()


def as_template_mapping(context: MaatlogTemplateContext) -> dict[str, Any]:
    """Convert *context* to a plain mapping for Jinja (stable public keys)."""
    return asdict(context)


def post_card_view(
    post: Post,
    *,
    page_url: str = "",
    image_url: str | None = None,
    slug: str | None = None,
) -> PostCardView:
    """Project a domain :class:`Post` into a list/card view."""
    return PostCardView(
        title=post.title,
        page_url=page_url,
        published_at=post.published_at,
        excerpt=post.excerpt,
        image_url=_resolve_image_url(post, image_url),
        tags=post.tags,
        categories=post.categories,
        authors=post.authors,
        external_url=post.external_url,
        slug=post.slug if slug is None else slug,
    )


def post_view(
    post: Post,
    *,
    body_html: str | None = None,
    page_url: str = "",
    image_url: str | None = None,
) -> PostView:
    """Project a domain :class:`Post` into a full post page view.

    External posts never expose ``body_html``; callers may still pass a body
    fragment, but it is discarded when ``post.external_url`` is set.

    *page_url* should be the absolute page URL when ``html_baseurl`` is known
    (Builder URI joined with the base). ``canonical_url`` falls back to that
    page URL when metadata does not set an explicit canonical.
    """
    resolved_body = None if post.external_url is not None else body_html
    urls = post_urls(page_url=page_url, canonical=post.canonical_url, external=post.external_url)
    canonical = urls.canonical_url if (page_url or post.canonical_url) else None
    return PostView(
        title=post.title,
        slug=post.slug,
        docname=post.docname,
        page_url=urls.page_url,
        canonical_url=canonical,
        external_url=urls.external_url,
        published_at=post.published_at,
        expires_at=post.expires_at,
        excerpt=post.excerpt,
        image_url=_resolve_image_url(post, image_url),
        tags=post.tags,
        categories=post.categories,
        authors=post.authors,
        body_html=resolved_body,
    )


def build_post_context(
    post: Post,
    *,
    body_html: str | None = None,
    page_url: str = "",
    image_url: str | None = None,
    navigation: NavigationView | None = None,
    feeds: tuple[FeedLinkView, ...] = (),
    taxonomies: TaxonomyNavigationView | None = None,
) -> MaatlogTemplateContext:
    """Build a ``page_kind="post"`` template context for *post*."""
    return MaatlogTemplateContext(
        page_kind="post",
        post=post_view(
            post,
            body_html=body_html,
            page_url=page_url,
            image_url=image_url,
        ),
        navigation=navigation if navigation is not None else NavigationView(None, None),
        feeds=feeds,
        taxonomies=taxonomies if taxonomies is not None else TaxonomyNavigationView.empty(),
    )


def archive_view(page: ArchivePage) -> ArchiveView:
    """Project an :class:`ArchivePage` into an :class:`ArchiveView`."""
    kind = "all" if page.key.axis is None else page.key.axis.value
    return ArchiveView(
        kind=kind,
        id=page.key.value,
        label=page.key.label,
        docname=page.docname,
        page_number=page.number,
        total_posts=page.total_posts,
    )


def pagination_view(
    page: ArchivePage,
    builder: Builder,
    *,
    all_pages: Sequence[ArchivePage],
) -> PaginationView:
    """Build pagination URLs relative to *page* via the Builder URI helpers."""
    siblings = {sibling.number: sibling.docname for sibling in all_pages if sibling.key == page.key}
    pages: list[tuple[int, str]] = []
    for number in range(1, page.total_pages + 1):
        target = siblings.get(number)
        if target is None:
            target = _sibling_docname(page, number)
        pages.append((number, relative_page_url_for(builder, page.docname, target)))

    previous_url: str | None = None
    next_url: str | None = None
    if page.number > 1:
        prev_doc = siblings.get(page.number - 1) or _sibling_docname(page, page.number - 1)
        previous_url = relative_page_url_for(builder, page.docname, prev_doc)
    if page.number < page.total_pages:
        next_doc = siblings.get(page.number + 1) or _sibling_docname(page, page.number + 1)
        next_url = relative_page_url_for(builder, page.docname, next_doc)

    return PaginationView(
        current=page.number,
        total_pages=page.total_pages,
        previous_url=previous_url,
        next_url=next_url,
        pages=tuple(pages),
    )


def archive_context(
    page: ArchivePage,
    builder: Builder,
    *,
    all_pages: Sequence[ArchivePage] | None = None,
    taxonomies: TaxonomyNavigationView | None = None,
    feeds: tuple[FeedLinkView, ...] = (),
) -> MaatlogTemplateContext:
    """Build a ``page_kind="archive"`` template context for *page*.

    Card and pagination URLs are relative to *page.docname* via
    :meth:`Builder.get_relative_uri`. Domain data is not modified.
    """
    pages = all_pages if all_pages is not None else (page,)
    cards = tuple(
        post_card_view(
            post,
            page_url=relative_page_url_for(builder, page.docname, post.docname),
            image_url=image_url_for(builder, page.docname, post.image_uri),
        )
        for post in page.posts
    )
    return MaatlogTemplateContext(
        page_kind="archive",
        posts=cards,
        archive=archive_view(page),
        pagination=pagination_view(page, builder, all_pages=pages),
        feeds=feeds,
        taxonomies=taxonomies if taxonomies is not None else TaxonomyNavigationView.empty(),
    )


def theme_can_resolve_template(app: Sphinx, name: str) -> bool:
    """Return True when the active HTML theme loader can load *name*."""
    templates = getattr(app.builder, "templates", None)
    if templates is None:
        return False
    environment = getattr(templates, "environment", None)
    if environment is None:
        return False
    try:
        environment.get_template(name)
    except TemplateNotFound:
        return False
    return True


def page_url_for(builder: Builder, docname: str) -> str:
    """Return the builder URI for *docname*, or empty string if unavailable."""
    try:
        return builder.get_target_uri(docname)
    except Exception:  # noqa: BLE001 — builders may raise for unknown docs
        return ""


def relative_page_url_for(builder: Builder, from_docname: str, to_docname: str) -> str:
    """Return a relative URI from *from_docname* to *to_docname*, or empty string."""
    try:
        return builder.get_relative_uri(from_docname, to_docname)
    except Exception:  # noqa: BLE001 — builders may raise NoUri / unknown docs
        return ""


def image_url_for(builder: Builder, from_docname: str, image_uri: str | None) -> str | None:
    """Resolve a representative image URI via the builder image map when possible.

    Representative images are registered on ``env.images`` during post collect
    even when they do not appear in the doctree. This helper promotes them into
    ``builder.images`` so Sphinx copies them to ``_images`` and returns a real
    builder-relative URI. Falls back to the raw *image_uri* only when the image
    is not registered with Sphinx at all.
    """
    if image_uri is None:
        return None
    dest_name = _ensure_builder_image(builder, image_uri)
    if dest_name is not None:
        imagedir = str(getattr(builder, "imagedir", "_images"))
        try:
            base = builder.get_target_uri(from_docname)
            img_root = relative_uri(base, imagedir)
        except Exception:  # noqa: BLE001 — builders may raise NoUri / unknown docs
            img_root = ""
        if img_root and not img_root.endswith("/"):
            return f"{img_root}/{dest_name}"
        return f"{img_root}{dest_name}" if img_root else dest_name
    return image_uri


def register_representative_images(app: Sphinx, builder: Builder) -> None:
    """Promote every MaatLog representative image on the master writer."""
    from .builders import is_full_html_builder

    if not is_full_html_builder(builder):
        return
    domain = app.env.get_domain("maatlog")
    posts = cast(dict[str, Post], domain.data.get("posts_by_docname", {}))
    for post in posts.values():
        if post.image_uri is not None:
            _ensure_builder_image(builder, post.image_uri)


def _ensure_builder_image(builder: Builder, image_uri: str) -> str | None:
    """Return the unique dest name for *image_uri*, registering on the builder if needed."""
    images_raw = getattr(builder, "images", None)
    if isinstance(images_raw, dict):
        images = cast(dict[str, str], images_raw)
        if image_uri in images:
            return images[image_uri]
        env = getattr(builder, "env", None)
        env_images = getattr(env, "images", None) if env is not None else None
        if env_images is not None and image_uri in env_images:
            dest_name = cast(str, env_images[image_uri][1])
            images[image_uri] = dest_name
            return dest_name
        return None
    if isinstance(images_raw, Mapping):
        images = cast(Mapping[str, str], images_raw)
        if image_uri in images:
            return images[image_uri]
    return None


def _sibling_docname(page: ArchivePage, number: int) -> str:
    """Derive the docname for page *number* of the same archive as *page*."""
    if number == page.number:
        return page.docname
    base = page.docname
    if page.number > 1:
        suffix = f"/page/{page.number}"
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    if number == 1:
        return base
    return f"{base}/page/{number}"


def _resolve_image_url(post: Post, image_url: str | None) -> str | None:
    if image_url is not None:
        return image_url
    return post.image_uri

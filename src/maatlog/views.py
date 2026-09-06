"""Stable, template-facing view models for the MaatLog Theme API context."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final, Literal, Self, cast

from jinja2 import TemplateNotFound
from sphinx.application import Sphinx
from sphinx.builders import Builder
from sphinx.util.osutil import relative_uri

from .archives import ArchivePage
from .authors import AuthorProfile
from .model import Post
from .theme_api import CORE_THEME_API
from .urls import is_absolute_http_url, post_urls
from .version import PACKAGE_VERSION

PageKind = Literal["normal", "post", "archive", "home", "profile"]

FEATURED_LIMIT: Final = 3


@dataclass(frozen=True, slots=True)
class FeedLinkView:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class AuthorLinkView:
    """One external author link. ``icon`` names a built-in MaatLog SVG icon."""

    type: str
    url: str
    label: str
    icon: str


@dataclass(frozen=True, slots=True)
class AuthorStatsView:
    """Build-time statistics of one author. Published posts only."""

    post_count: int
    writing_since: int | None
    latest_post: datetime | None


@dataclass(frozen=True, slots=True)
class SiteView:
    title: str
    tagline: str | None
    archive_url: str
    top_image_title_font: str | None = None
    content_width: str | None = None


@dataclass(frozen=True, slots=True)
class TaxonomyLinkView:
    """One taxonomy value on a post or card. ``url`` is empty when unresolvable."""

    id: str
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class PostTaxonomiesView:
    tags: tuple[TaxonomyLinkView, ...]
    categories: tuple[TaxonomyLinkView, ...]
    authors: tuple[TaxonomyLinkView, ...]

    @classmethod
    def empty(cls) -> Self:
        return cls((), (), ())


@dataclass(frozen=True, slots=True)
class TaxonomyItemView:
    id: str
    label: str
    count: int
    url: str
    #: このページがこの分類のアーカイブ（ページ送りを含む）かどうか。
    is_current: bool = False


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
    taxonomies: PostTaxonomiesView = PostTaxonomiesView.empty()


@dataclass(frozen=True, slots=True)
class AuthorSummaryView:
    """One author as the right rail draws them.

    Deliberately lighter than :class:`AuthorProfileView`: the About body, the
    featured cards and the statistics are profile-page data and would cost a
    doctree re-render on every page of the site.

    ``profile_url`` is empty when the author has no published post, because no
    author archive page is generated for them.
    """

    slug: str
    display_name: str
    avatar_url: str | None
    initials: str
    bio_short: str | None
    links: tuple[AuthorLinkView, ...]
    profile_url: str


@dataclass(frozen=True, slots=True)
class AuthorProfileView:
    """Everything a profile page renders for one author.

    ``about_html`` is the About document rendered for the profile page's own
    location, so its relative URIs are already correct. ``initials`` is filled
    even when ``avatar_url`` is set, so a theme can choose either.
    """

    slug: str
    display_name: str
    role: str | None
    avatar_url: str | None
    initials: str
    bio_short: str | None
    interests: tuple[str, ...]
    links: tuple[AuthorLinkView, ...]
    about_html: str | None
    featured: tuple[PostCardView, ...]
    stats: AuthorStatsView


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
    top_image_url: str | None = None
    top_image_alt: str = ""
    taxonomies: PostTaxonomiesView = PostTaxonomiesView.empty()


@dataclass(frozen=True, slots=True)
class ArchiveView:
    kind: str
    id: str | None
    label: str
    docname: str
    page_number: int
    total_posts: int
    is_home: bool = False


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
    api_version: str = str(CORE_THEME_API)
    version: str = PACKAGE_VERSION
    page_kind: PageKind = "normal"
    post: PostView | None = None
    posts: tuple[PostCardView, ...] = ()
    featured: tuple[PostCardView, ...] = ()
    latest: tuple[PostCardView, ...] = ()
    archive: ArchiveView | None = None
    pagination: PaginationView | None = None
    navigation: NavigationView = NavigationView(None, None)
    feeds: tuple[FeedLinkView, ...] = ()
    taxonomies: TaxonomyNavigationView = TaxonomyNavigationView.empty()
    site: SiteView = SiteView("", None, "")
    profile: AuthorProfileView | None = None
    author_summaries: tuple[AuthorSummaryView, ...] = ()


def author_link_views(profile: AuthorProfile | None) -> tuple[AuthorLinkView, ...]:
    """Return the template-facing links of *profile* in configuration order."""
    if profile is None:
        return ()
    return tuple(
        AuthorLinkView(type=link.type, url=link.url, label=link.label, icon=link.icon) for link in profile.links
    )


def empty_context(site: SiteView | None = None) -> MaatlogTemplateContext:
    """Return a fully-keyed normal-page context with empty / None values."""
    if site is None:
        return MaatlogTemplateContext()
    return MaatlogTemplateContext(site=site)


def normal_page_context(
    *,
    site: SiteView | None = None,
    taxonomies: TaxonomyNavigationView | None = None,
    feeds: tuple[FeedLinkView, ...] = (),
    author_summaries: tuple[AuthorSummaryView, ...] = (),
) -> MaatlogTemplateContext:
    """Return the context for a page that is neither a post, archive, nor home.

    Theme API 1.2 guarantees ``taxonomies`` and ``feeds`` on every full-HTML
    page so themes can render one site-wide navigation sidebar. ``page_kind``
    stays ``"normal"``; 1.0 and 1.1 themes simply ignore the extra data.
    """
    return MaatlogTemplateContext(
        site=site if site is not None else SiteView("", None, ""),
        taxonomies=taxonomies if taxonomies is not None else TaxonomyNavigationView.empty(),
        feeds=feeds,
        author_summaries=author_summaries,
    )


def as_template_mapping(context: MaatlogTemplateContext) -> dict[str, Any]:
    """Convert *context* to a plain mapping for Jinja (stable public keys)."""
    return asdict(context)


def post_card_view(
    post: Post,
    *,
    page_url: str = "",
    image_url: str | None = None,
    slug: str | None = None,
    taxonomies: PostTaxonomiesView | None = None,
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
        taxonomies=taxonomies if taxonomies is not None else PostTaxonomiesView.empty(),
    )


def post_view(
    post: Post,
    *,
    body_html: str | None = None,
    page_url: str = "",
    image_url: str | None = None,
    top_image_url: str | None = None,
    top_image_alt: str = "",
    taxonomies: PostTaxonomiesView | None = None,
) -> PostView:
    """Project a domain :class:`Post` into a full post page view.

    External posts never expose ``body_html``; callers may still pass a body
    fragment, but it is discarded when ``post.external_url`` is set.

    *page_url* should be the absolute page URL when ``html_baseurl`` is known
    (Builder URI joined with the base). ``canonical_url`` falls back to that
    page URL when metadata does not set an explicit canonical.

    ``canonical_url`` stays ``None`` unless the resolved value is an absolute
    URL. Without ``html_baseurl`` the fallback is the builder target URI, and a
    relative canonical is invalid: browsers resolve it against the document, so
    a post below the root would advertise — and share — an unreachable URL.
    """
    resolved_body = None if post.external_url is not None else body_html
    urls = post_urls(page_url=page_url, canonical=post.canonical_url, external=post.external_url)
    canonical = urls.canonical_url if is_absolute_http_url(urls.canonical_url) else None
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
        top_image_url=top_image_url,
        top_image_alt=top_image_alt,
        taxonomies=taxonomies if taxonomies is not None else PostTaxonomiesView.empty(),
    )


def build_post_context(
    post: Post,
    *,
    body_html: str | None = None,
    page_url: str = "",
    image_url: str | None = None,
    top_image_url: str | None = None,
    top_image_alt: str = "",
    navigation: NavigationView | None = None,
    feeds: tuple[FeedLinkView, ...] = (),
    taxonomies: TaxonomyNavigationView | None = None,
    site: SiteView | None = None,
    post_taxonomies: PostTaxonomiesView | None = None,
    author_summaries: tuple[AuthorSummaryView, ...] = (),
) -> MaatlogTemplateContext:
    """Build a ``page_kind="post"`` template context for *post*."""
    return MaatlogTemplateContext(
        page_kind="post",
        post=post_view(
            post,
            body_html=body_html,
            page_url=page_url,
            image_url=image_url,
            top_image_url=top_image_url,
            top_image_alt=top_image_alt,
            taxonomies=post_taxonomies,
        ),
        navigation=navigation if navigation is not None else NavigationView(None, None),
        feeds=feeds,
        taxonomies=taxonomies if taxonomies is not None else TaxonomyNavigationView.empty(),
        site=site if site is not None else SiteView("", None, ""),
        author_summaries=author_summaries,
    )


def archive_view(page: ArchivePage, *, is_home: bool = False) -> ArchiveView:
    """Project an :class:`ArchivePage` into an :class:`ArchiveView`."""
    kind = "all" if page.key.axis is None else page.key.axis.value
    return ArchiveView(
        kind=kind,
        id=page.key.value,
        label=page.key.label,
        docname=page.docname,
        page_number=page.number,
        total_posts=page.total_posts,
        is_home=is_home,
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
    site: SiteView | None = None,
    linker: Callable[[Post], PostTaxonomiesView] | None = None,
    is_home: bool = False,
    profile: AuthorProfileView | None = None,
    author_summaries: tuple[AuthorSummaryView, ...] = (),
    featured_posts: Sequence[Post] | None = None,
) -> MaatlogTemplateContext:
    """Build a ``page_kind="archive"`` template context for *page*.

    Card and pagination URLs are relative to *page.docname* via
    :meth:`Builder.get_relative_uri`. Domain data is not modified.

    Passing *profile* turns the page into ``page_kind="profile"``. Everything
    else (cards, pagination, feeds, taxonomies) stays identical, so a profile
    page is an author archive with a profile header on top.

    ``author_summaries`` は呼び出し側が決める。``profile`` が渡ったページ
    （``page_kind="profile"``）では空タプルを渡すこと。プロフィールページは
    右ペインを出さない。
    """
    pages = all_pages if all_pages is not None else (page,)
    cards = tuple(
        post_card_view(
            post,
            page_url=relative_page_url_for(builder, page.docname, post.docname),
            image_url=image_url_for(builder, page.docname, post.image_uri),
            taxonomies=linker(post) if linker is not None else None,
        )
        for post in page.posts
    )
    featured: tuple[PostCardView, ...] = ()
    latest: tuple[PostCardView, ...] = ()
    if is_home:
        featured_cards = None
        if featured_posts is not None:
            featured_cards = tuple(
                post_card_view(
                    item,
                    page_url=relative_page_url_for(builder, page.docname, item.docname),
                    image_url=image_url_for(builder, page.docname, item.image_uri),
                    taxonomies=linker(item) if linker is not None else None,
                )
                for item in featured_posts
            )
        featured, latest = project_featured_latest(cards, featured=featured_cards)
    return MaatlogTemplateContext(
        page_kind="profile" if profile is not None else "archive",
        posts=cards,
        featured=featured,
        latest=latest,
        archive=archive_view(page, is_home=is_home),
        pagination=pagination_view(page, builder, all_pages=pages),
        feeds=feeds,
        taxonomies=taxonomies if taxonomies is not None else TaxonomyNavigationView.empty(),
        site=site if site is not None else SiteView("", None, ""),
        profile=profile,
        author_summaries=author_summaries,
    )


def project_featured_latest(
    eligible: Sequence[PostCardView],
    *,
    featured: Sequence[PostCardView] | None = None,
    latest_limit: int | None = None,
) -> tuple[tuple[PostCardView, ...], tuple[PostCardView, ...]]:
    """Split *eligible* into displayed featured cards and the leftover latest column."""
    chosen = tuple(eligible[:FEATURED_LIMIT] if featured is None else featured[:FEATURED_LIMIT])
    chosen_slugs = {card.slug for card in chosen if card.slug is not None}
    rest = tuple(card for card in eligible if card.slug not in chosen_slugs)
    if latest_limit is not None:
        rest = rest[:latest_limit]
    return chosen, rest


def home_context(
    published: Sequence[Post],
    builder: Builder,
    *,
    docname: str,
    page_size: int,
    site: SiteView,
    label: str = "Posts",
    linker: Callable[[Post], PostTaxonomiesView] | None = None,
    taxonomies: TaxonomyNavigationView | None = None,
    feeds: tuple[FeedLinkView, ...] = (),
    author_summaries: tuple[AuthorSummaryView, ...] = (),
    featured_posts: Sequence[Post] | None = None,
) -> MaatlogTemplateContext:
    """Build a ``page_kind="home"`` context for the blog home page.

    The home page has no pagination: it shows up to ``FEATURED_LIMIT`` featured
    cards plus up to ``page_size`` latest cards (``posts == featured + latest``)
    and directs the reader to the archive root via ``site.archive_url``. Archive
    projection (:func:`project_archives`) is deliberately not used.
    """

    def _to_card(item: Post) -> PostCardView:
        return post_card_view(
            item,
            page_url=relative_page_url_for(builder, docname, item.docname),
            image_url=image_url_for(builder, docname, item.image_uri),
            taxonomies=linker(item) if linker is not None else None,
        )

    visible_posts = tuple(item for item in published if item.docname != docname)
    # Only build cards for the window the projection can consume: featured (max
    # ``FEATURED_LIMIT``) plus up to ``page_size`` latest cards.
    eligible_cards = tuple(_to_card(item) for item in visible_posts[: FEATURED_LIMIT + page_size])
    featured_cards = None
    if featured_posts is not None:
        featured_cards = tuple(_to_card(item) for item in featured_posts if item.docname != docname)
    featured, latest = project_featured_latest(
        eligible_cards,
        featured=featured_cards,
        latest_limit=page_size,
    )
    cards = featured + latest
    return MaatlogTemplateContext(
        page_kind="home",
        posts=cards,
        featured=featured,
        latest=latest,
        archive=ArchiveView(
            kind="all",
            id=None,
            label=label,
            docname=docname,
            page_number=1,
            total_posts=len(published),
            is_home=True,
        ),
        pagination=None,
        feeds=feeds,
        taxonomies=taxonomies if taxonomies is not None else TaxonomyNavigationView.empty(),
        site=site,
        author_summaries=author_summaries,
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
    """Promote every MaatLog representative and hero image on the master writer.

    Both kinds live outside the doctree by the time Sphinx runs
    ``post_process_images``: representative images never enter it, and
    ``maattop_node`` is removed during ``doctree-read``. ``image_url_for`` would
    promote them, but it runs on ``html-page-context`` — a worker process under
    ``-j`` — so its ``builder.images`` writes never reach the master that copies
    files. Promoting here keeps ``_images`` complete for parallel writes.

    Author avatars are promoted for a stronger reason: they are configured, never
    appear in any doctree, and are drawn only by generated profile pages, so no
    ``post_process_images`` pass would ever register them on the builder.
    """
    from .builders import is_full_html_builder

    if not is_full_html_builder(builder):
        return
    domain = app.env.get_domain("maatlog")
    posts = cast(dict[str, Post], domain.data.get("posts_by_docname", {}))
    for post in posts.values():
        if post.image_uri is not None:
            _ensure_builder_image(builder, post.image_uri)
    maattop = cast(dict[str, dict[str, str]], domain.data.get("maattop_by_docname", {}))
    for entry in maattop.values():
        _ensure_builder_image(builder, entry["uri"])
    for relative in _resolved_avatar_paths(app):
        _ensure_builder_image(builder, relative)


def _resolved_avatar_paths(app: Sphinx) -> tuple[str, ...]:
    """Srcdir-relative avatar paths resolved during ``env-updated``.

    Read through ``getattr`` because :mod:`maatlog.extension` imports this module;
    importing it back would be circular.
    """
    profiles = getattr(app, "_maatlog_resolved_profiles", None)
    avatars = getattr(profiles, "avatars", None)
    if not isinstance(avatars, Mapping):
        return ()
    return tuple(cast(Mapping[str, str], avatars).values())


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

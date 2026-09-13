"""Post social metadata projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..urls import resolve_crawler_url
from .serialization import serialize_json_ld
from .views import OpenGraphPropertyView, SocialMetadataView, TwitterCardPropertyView

if TYPE_CHECKING:
    from maatlog.views import MaatlogTemplateContext, PostView, TaxonomyLinkView

#: The JSON-LD vocabulary this projector emits against.
SCHEMA_CONTEXT = "https://schema.org"


def project_post_metadata(
    context: MaatlogTemplateContext,
    *,
    page_url: str | None,
) -> SocialMetadataView:
    post = context.post
    if post is None:
        return SocialMetadataView()
    image = _social_image(post, page_url=page_url)
    if post.external_url is not None:
        return _external_post_view(post, context, image)
    return _internal_post_view(post, context, image, page_url=page_url)


def _external_post_view(
    post: PostView,
    context: MaatlogTemplateContext,
    image: _SocialImage | None,
) -> SocialMetadataView:
    """An external post is shared as a website summary, never as MaatLog's own article.

    MaatLog does not host the body, so it emits no ``BlogPosting`` and no ``article:*``
    property. The shared URL is the external one — the same role ``PostUrls.primary_url``
    gives it — while the local canonical link keeps pointing at the local page.
    """
    title = _text(post.title)
    description = _text(post.excerpt)
    return SocialMetadataView(
        open_graph=_open_graph(
            (
                ("og:type", "website"),
                ("og:title", title),
                ("og:site_name", _text(context.site.title)),
                ("og:url", resolve_crawler_url(post.external_url)),
                ("og:description", description),
                ("og:image", None if image is None else image.url),
                ("og:image:alt", None if image is None else image.alt),
            )
        ),
        twitter=_twitter(title=title, description=description, image=image),
    )


def _internal_post_view(
    post: PostView,
    context: MaatlogTemplateContext,
    image: _SocialImage | None,
    *,
    page_url: str | None,
) -> SocialMetadataView:
    """Project an internally hosted post as MaatLog's own article."""
    title = _text(post.title)
    description = _text(post.excerpt)
    url = _internal_url(post, page_url)
    published = _published(post)
    tags = _labels(post.taxonomies.tags, post.tags)
    sections = _labels(post.taxonomies.categories, post.categories)
    candidates: tuple[tuple[str, str | None], ...] = (
        ("og:type", "article"),
        ("og:title", title),
        ("og:site_name", _text(context.site.title)),
        ("og:url", url),
        ("og:description", description),
        ("og:image", None if image is None else image.url),
        ("og:image:alt", None if image is None else image.alt),
        ("article:published_time", published),
        *(("article:tag", tag) for tag in tags),
        *(("article:section", section) for section in sections),
    )
    return SocialMetadataView(
        open_graph=_open_graph(candidates),
        twitter=_twitter(title=title, description=description, image=image),
        json_ld=_blog_posting(
            title=title,
            description=description,
            published=published,
            url=url,
            image=image,
            people=_people(context, page_url=page_url),
            keywords=tags,
            sections=sections,
        ),
    )


def _people(context: MaatlogTemplateContext, *, page_url: str | None) -> list[dict[str, object]]:
    """One ``Person`` per author the post itself declares, in the post's own order.

    Names come from the resolved ``AuthorSummaryView``: MaatLog already resolves a display
    name from ``maatlog_authors``, then the taxonomy label, then the id, and the metadata
    must show the same name the page shows. The id is used only when the page carries no
    summary for that author at all, or when that summary's display name is blank — the
    resolved display name is preferred whenever a non-blank one exists.

    ``context.author_summaries`` falls back to ``maatlog_default_author`` for a post that
    names nobody, so an author is claimed only when ``post.authors`` lists it.
    """
    post = context.post
    if post is None:
        return []
    summaries = {summary.slug: summary for summary in context.author_summaries}
    people: list[dict[str, object]] = []
    for author_id in post.authors:
        found = summaries.get(author_id)
        name = _text(author_id) if found is None else _text(found.display_name) or _text(author_id)
        if name is None:
            continue
        person: dict[str, object] = {"@type": "Person", "name": name}
        profile_url = None if found is None else resolve_crawler_url(found.profile_url, page_url=page_url)
        if profile_url is not None:
            person["url"] = profile_url
        people.append(person)
    return people


def _blog_posting(
    *,
    title: str | None,
    description: str | None,
    published: str | None,
    url: str | None,
    image: _SocialImage | None,
    people: list[dict[str, object]],
    keywords: tuple[str, ...],
    sections: tuple[str, ...],
) -> str | None:
    """Serialize the post as ``BlogPosting``; ``None`` when it has no headline.

    ``headline`` is the one value schema.org cannot do without here, and MaatLog has no
    second source for it, so a titleless post gets no JSON-LD rather than an empty one.
    Optional keys are added only when their value exists, so no key ever carries ``null``,
    ``""`` or ``[]``.
    """
    if title is None:
        return None
    document: dict[str, object] = {
        "@context": SCHEMA_CONTEXT,
        "@type": "BlogPosting",
        "headline": title,
    }
    optional: tuple[tuple[str, object], ...] = (
        ("description", description),
        ("datePublished", published),
        ("url", url),
        ("image", [] if image is None else [image.url]),
        ("author", people),
        ("keywords", list(keywords)),
        ("articleSection", list(sections)),
    )
    for key, value in optional:
        if value:
            document[key] = value
    return serialize_json_ld(document)


@dataclass(frozen=True, slots=True)
class _SocialImage:
    """The one image this page shares, already absolute, with its own description."""

    url: str
    alt: str | None


def _social_image(post: PostView, *, page_url: str | None) -> _SocialImage | None:
    """Pick the representative image, else the ``maattop`` hero, else nothing.

    The chosen candidate is not replaced when it cannot be absolutized: both candidates
    are builder-relative URIs resolved against the same page URL, so a failure means the
    page URL itself is unusable and the next candidate would fail for the same reason.

    ``maatlog-image`` has no description field, so only the ``maattop`` hero can carry an
    alt. The post title is never reused as a description of the image.
    """
    representative = _text(post.image_url)
    if representative is not None:
        candidate, alt = representative, None
    else:
        top = _text(post.top_image_url)
        if top is None:
            return None
        candidate, alt = top, _text(post.top_image_alt)
    url = resolve_crawler_url(candidate, page_url=page_url)
    return None if url is None else _SocialImage(url=url, alt=alt)


def _twitter(
    *,
    title: str | None,
    description: str | None,
    image: _SocialImage | None,
) -> tuple[TwitterCardPropertyView, ...]:
    items: tuple[tuple[str, str | None], ...] = (
        ("twitter:card", "summary" if image is None else "summary_large_image"),
        ("twitter:title", title),
        ("twitter:description", description),
        ("twitter:image", None if image is None else image.url),
        ("twitter:image:alt", None if image is None else image.alt),
    )
    return tuple(TwitterCardPropertyView(name=name, content=content) for name, content in items if content is not None)


def _text(value: str | None) -> str | None:
    """Return *value* without surrounding whitespace, or ``None`` when it carries nothing.

    ``None``, ``""`` and whitespace-only values all mean "this post does not have it",
    so they collapse to one absent case instead of emitting an empty ``content``.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _internal_url(post: PostView, page_url: str | None) -> str | None:
    """The crawler-facing URL of an internal post: explicit canonical, else the page URL.

    ``PostView.canonical_url`` is already the explicit canonical or the absolute page
    URL, so the second candidate only matters when a build resolves a page URL that the
    view layer did not. Both go through ``resolve_crawler_url`` so a relative value can
    never reach the output.
    """
    for candidate in (post.canonical_url, page_url):
        resolved = resolve_crawler_url(candidate, page_url=page_url)
        if resolved is not None:
            return resolved
    return None


def _published(post: PostView) -> str | None:
    """ISO 8601 publication time. ``parse_datetime`` guarantees it is timezone-aware."""
    return None if post.published_at is None else post.published_at.isoformat()


def _labels(links: tuple[TaxonomyLinkView, ...], ids: tuple[str, ...]) -> tuple[str, ...]:
    """Display labels for one taxonomy axis, falling back to the ids.

    ``PostTaxonomyLinker.for_post`` yields one link per id in source order, so a length
    mismatch only happens when the build has no taxonomy index and the view carries the
    empty projection. The ids are what the page itself shows in that case.
    """
    values = ids if len(links) != len(ids) else tuple(link.label for link in links)
    return tuple(text for text in (_text(value) for value in values) if text is not None)


def _open_graph(items: tuple[tuple[str, str | None], ...]) -> tuple[OpenGraphPropertyView, ...]:
    return tuple(
        OpenGraphPropertyView(property=name, content=content) for name, content in items if content is not None
    )

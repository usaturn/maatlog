"""Author profile social metadata projection.

Owned by issue #210. ``maatlog.views`` imports this package at runtime, so
``MaatlogTemplateContext`` and the profile views stay behind ``TYPE_CHECKING``:
importing them back would close the cycle and break the build.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maatlog.urls import resolve_crawler_url

from .serialization import serialize_json_ld
from .views import OpenGraphPropertyView, SocialMetadataView, TwitterCardPropertyView

if TYPE_CHECKING:
    from maatlog.views import AuthorLinkView, MaatlogTemplateContext

SCHEMA_CONTEXT = "https://schema.org"


def project_profile_metadata(
    context: MaatlogTemplateContext,
    *,
    page_url: str | None,
) -> SocialMetadataView:
    """Project one author profile page into its social metadata view.

    ``page_kind == "profile"`` is reached only for page 1 of an author who has a
    ``maatlog_author_profiles`` entry, so page 2 and beyond — and authors without a
    profile — never produce profile metadata.
    """
    profile = context.profile
    if profile is None:
        return SocialMetadataView()
    display_name = _text(profile.display_name)
    description = _text(profile.bio_short)
    site_name = _text(context.site.title)
    image_url = resolve_crawler_url(profile.avatar_url, page_url=page_url)
    same_as = _same_as(profile.links)
    return SocialMetadataView(
        open_graph=_open_graph(
            display_name=display_name,
            site_name=site_name,
            page_url=page_url,
            description=description,
            image_url=image_url,
        ),
        twitter=_twitter(display_name=display_name, description=description, image_url=image_url),
        json_ld=_json_ld(
            display_name=display_name,
            description=description,
            image_url=image_url,
            page_url=page_url,
            same_as=same_as,
        ),
    )


def _text(value: str | None) -> str | None:
    """Return *value* stripped, or ``None`` when it carries no text.

    A ``content=""`` meta tag says "this site has no title" rather than "unknown", so
    a blank configuration value has to drop the property instead of emitting it empty.
    """
    if value is None:
        return None
    return value.strip() or None


def _open_graph(
    *,
    display_name: str | None,
    site_name: str | None,
    page_url: str | None,
    description: str | None,
    image_url: str | None,
) -> tuple[OpenGraphPropertyView, ...]:
    """Build the Open Graph properties, dropping every value MaatLog does not have.

    ``og:image:alt`` and the ``profile:*`` properties are deliberately absent: no avatar
    description is configurable, display names do not split reliably into given and
    family names, and ``profile:username`` would publish the internal author id.
    """
    candidates = (
        ("og:type", "profile"),
        ("og:title", display_name),
        ("og:site_name", site_name),
        ("og:url", page_url),
        ("og:description", description),
        ("og:image", image_url),
    )
    return tuple(
        OpenGraphPropertyView(property=name, content=content) for name, content in candidates if content is not None
    )


def _twitter(
    *,
    display_name: str | None,
    description: str | None,
    image_url: str | None,
) -> tuple[TwitterCardPropertyView, ...]:
    """Build the X Card properties.

    The card stays ``summary`` with or without an avatar: an avatar is a square
    portrait, not the wide image ``summary_large_image`` is meant for.
    """
    candidates = (
        ("twitter:card", "summary"),
        ("twitter:title", display_name),
        ("twitter:description", description),
        ("twitter:image", image_url),
    )
    return tuple(
        TwitterCardPropertyView(name=name, content=content) for name, content in candidates if content is not None
    )


def _same_as(links: tuple[AuthorLinkView, ...]) -> tuple[str, ...]:
    """Return the external links that survive the shared crawler URL gate.

    ``authors._validate_link`` already rejects a non-absolute link at configuration
    time; running the values through :func:`resolve_crawler_url` anyway keeps every
    crawler-facing URL in this projector on one code path. Configuration order is
    preserved and a duplicate is kept: dropping a value the author configured twice
    would be the projector editing the site's own data.
    """
    resolved = (resolve_crawler_url(link.url) for link in links)
    return tuple(url for url in resolved if url is not None)


def _json_ld(
    *,
    display_name: str | None,
    description: str | None,
    image_url: str | None,
    page_url: str | None,
    same_as: tuple[str, ...],
) -> str | None:
    """Serialize the ``ProfilePage`` document, or ``None`` when the person has no name.

    ``Person.name`` is required, so an author whose display name carries no text gets no
    document rather than a placeholder. A display name that equals the author slug is
    still a public name — it is the same heading the profile page shows when
    ``maatlog_authors`` is ``None`` — and must not drop the document.
    ``dateCreated`` / ``dateModified`` are never produced — source mtime, Git and
    build time all describe something other than when the profile changed — and
    neither are schema.org properties for ``role`` and ``interests``, which are
    free text that would change meaning once typed.

    ``description`` / ``image`` / ``url`` / ``sameAs`` all describe the person, so they
    belong on ``mainEntity``. The page's own URL is already carried by ``og:url`` and
    the canonical link.
    """
    if display_name is None:
        return None
    person: dict[str, object] = {"@type": "Person", "name": display_name}
    if description is not None:
        person["description"] = description
    if image_url is not None:
        person["image"] = image_url
    if page_url is not None:
        person["url"] = page_url
    if same_as:
        person["sameAs"] = list(same_as)
    return serialize_json_ld({"@context": SCHEMA_CONTEXT, "@type": "ProfilePage", "mainEntity": person})

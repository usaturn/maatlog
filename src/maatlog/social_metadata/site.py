"""Blog top and archive metadata projection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .serialization import serialize_json_ld
from .views import OpenGraphPropertyView, SocialMetadataView, TwitterCardPropertyView

if TYPE_CHECKING:
    from maatlog.views import ArchiveView, MaatlogTemplateContext, SiteView


def project_site_metadata(
    context: MaatlogTemplateContext,
    *,
    page_url: str | None,
) -> SocialMetadataView:
    """Project the blog top or one archive page into its social metadata view.

    ``archive.is_home`` is the single source of truth for "this page is the blog top".
    A configured home (``page_kind="home"``) and the archive root that takes over when
    no home is configured (``page_kind="archive"``) both set it, and ``extension.py``
    guarantees at most one page in the site does, so keying on ``page_kind`` here would
    silently miss the fallback.
    """
    archive = context.archive
    if archive is None:
        return SocialMetadataView()
    if archive.is_home:
        return _blog_top_view(context.site, archive, page_url)
    return _archive_view(context.site, archive, page_url)


def _text(value: str | None) -> str | None:
    """Return *value* stripped, or None when it carries no text."""
    if value is None:
        return None
    return value.strip() or None


def _blog_top_view(site: SiteView, archive: ArchiveView, page_url: str | None) -> SocialMetadataView:
    site_title = _text(site.title)
    # The blog top speaks for the whole site, so its title is the site title. The archive
    # label ("Posts") is this page's own real title and stands in when the site has no
    # name; it never becomes the WebSite name, which has to be the site's name or nothing.
    title = site_title or _text(archive.label)
    if title is None:
        return SocialMetadataView()
    description = _text(site.tagline)
    open_graph = [
        OpenGraphPropertyView(property="og:type", content="website"),
        OpenGraphPropertyView(property="og:title", content=title),
    ]
    twitter = [
        TwitterCardPropertyView(name="twitter:card", content="summary"),
        TwitterCardPropertyView(name="twitter:title", content=title),
    ]
    if description is not None:
        open_graph.append(OpenGraphPropertyView(property="og:description", content=description))
        twitter.append(TwitterCardPropertyView(name="twitter:description", content=description))
    if page_url is not None:
        open_graph.append(OpenGraphPropertyView(property="og:url", content=page_url))
    return SocialMetadataView(
        open_graph=tuple(open_graph),
        twitter=tuple(twitter),
        json_ld=_website_json_ld(site_title, page_url, description),
    )


def _archive_view(site: SiteView, archive: ArchiveView, page_url: str | None) -> SocialMetadataView:
    """Project one archive page. No JSON-LD: CollectionPage / ItemList are out of scope.

    The title is the archive's own label, so ``og:site_name`` is what tells a crawler
    which site the page belongs to. No description is emitted: an archive has no
    explicit description field, and reusing the site tagline would make every archive
    claim the same one. An empty label yields an empty view even when the site title
    and page URL are present: there is no page title to hang those properties on
    (Spec §4.4).
    """
    title = _text(archive.label)
    if title is None:
        return SocialMetadataView()
    open_graph = [
        OpenGraphPropertyView(property="og:type", content="website"),
        OpenGraphPropertyView(property="og:title", content=title),
    ]
    site_title = _text(site.title)
    if site_title is not None:
        open_graph.append(OpenGraphPropertyView(property="og:site_name", content=site_title))
    if page_url is not None:
        open_graph.append(OpenGraphPropertyView(property="og:url", content=page_url))
    return SocialMetadataView(
        open_graph=tuple(open_graph),
        twitter=(
            TwitterCardPropertyView(name="twitter:card", content="summary"),
            TwitterCardPropertyView(name="twitter:title", content=title),
        ),
    )


def _website_json_ld(name: str | None, page_url: str | None, description: str | None) -> str | None:
    """Serialize the ``WebSite`` object, or None when the site has no name.

    ``name`` is required by schema.org. It is the site title only: the archive label
    that ``_blog_top_view`` falls back to for ``og:title`` is this page's title, not the
    site's name, so a site without a title gets no ``WebSite`` at all.
    """
    if name is None:
        return None
    data: dict[str, object] = {"@context": "https://schema.org", "@type": "WebSite", "name": name}
    if page_url is not None:
        data["url"] = page_url
    if description is not None:
        data["description"] = description
    return serialize_json_ld(data)

from __future__ import annotations

import json
import os
import pickle
from collections.abc import Collection, Iterable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from docutils import nodes
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.config import Config
from sphinx.environment import BuildEnvironment
from sphinx.highlighting import PygmentsBridge
from sphinx.util import logging
from sphinx.util.typing import ExtensionMetadata

from .archives import ArchivePage, check_generated_docnames, project_archives
from .builders import (
    BuilderCapability,
    builder_capability,
    is_full_html_builder,
    warn_partial_support_once,
)
from .clock import resolve_build_time
from .config import MaatlogConfig, TaxonomyAxis, register_config
from .directives import (
    html_depart_post_list,
    html_visit_post_list,
    latex_visit_post_list,
    maattop_node,
    post_list,
    process_post_list_nodes,
    text_visit_post_list,
)
from .domain import MaatlogDomain
from .errors import MaatlogBuildError
from .feeds import write_feeds_after_success
from .html_metadata import (
    absolute_doc_url,
    archive_feed_links,
    capture_internal_body,
    cleanup_body_fragment_store,
    discovery_feeds_enabled,
    ensure_feed_baseurl,
    force_post_docs_outdated_for_feeds,
    format_post_date,
    post_feed_links,
    prepare_body_fragment_store,
    resolved_baseurl,
)
from .metadata import capture_source, cleanup_sources, collect_maattop_from_myst, collect_post
from .model import Post
from .navigation import PostTaxonomyLinker, neighbors, post_taxonomy_linker, taxonomy_navigation
from .outputs import commit_page_outputs
from .profiles import (
    ResolvedProfiles,
    author_summary_views,
    build_profile_view,
    mark_about_documents_orphan,
    profile_docname,
    register_avatars,
    resolve_profiles,
)
from .taxonomy import DomainIndex
from .theme_api import resolve_palette, resolve_pygments_style, validate_selected_theme
from .version import PACKAGE_VERSION
from .views import (
    AuthorProfileView,
    AuthorSummaryView,
    FeedLinkView,
    NavigationView,
    PostCardView,
    SiteView,
    TaxonomyLinkView,
    archive_context,
    as_template_mapping,
    build_post_context,
    empty_context,
    home_context,
    image_url_for,
    normal_page_context,
    post_card_view,
    register_representative_images,
    relative_page_url_for,
    theme_can_resolve_template,
)

logger = logging.getLogger(__name__)

POST_TEMPLATE = "maatlog/post.html"
ARCHIVE_TEMPLATE = "maatlog/archive.html"
HOME_TEMPLATE = "maatlog/home.html"
PROFILE_TEMPLATE = "maatlog/profile.html"
_THEMES_DIR = Path(__file__).resolve().parent / "themes"


def _register_bundled_themes(app: Sphinx) -> None:
    """Register official MaatLog HTML themes shipped as package data."""
    for name in ("maatlog-base", "maatlog-default"):
        path = _THEMES_DIR / name
        if path.is_dir():
            app.add_html_theme(name, str(path))


def link_palette_stylesheet(app: Sphinx) -> None:
    """Link the selected palette's CSS after the theme stylesheet.

    Extension priority (500) puts it after the theme's own ``maatlog.css``
    (priority 200), so palette tokens win by source order. Nothing is linked
    for the theme's default palette: those values already live in
    ``static/maatlog.css``.
    """
    stylesheet = resolve_palette(app)
    if stylesheet is None:
        return
    app.add_css_file(stylesheet, priority=500)


def apply_pygments_style(app: Sphinx) -> None:
    """Swap the builder's highlighters for the palette's Pygments style.

    ``StandaloneHTMLBuilder.init_highlighter`` runs inside ``builder.init()``,
    before ``builder-inited``, and takes the dark style from the theme only.
    Replacing the bridges here still lands: ``create_pygments_style_file`` reads
    them in the finish phase.

    ``dark_highlighter`` is swapped only when the builder already has one.
    ``init_css_files`` registers the ``pygments_dark.css`` link during
    ``init()``; creating a dark highlighter now would write a stylesheet that
    no page links, and clearing one would leave a link with nothing behind it.
    """
    style = resolve_pygments_style(app)
    if style is None:
        return
    builder: Any = app.builder
    if getattr(builder, "highlighter", None) is None:
        return
    builder.highlighter = PygmentsBridge("html", style)
    if getattr(builder, "dark_highlighter", None) is not None:
        builder.dark_highlighter = PygmentsBridge("html", style)


def initialize_build_time(app: Sphinx, config: Config) -> None:
    del config
    if "_maatlog_build_time" not in app.__dict__:
        app.__dict__["_maatlog_build_time"] = resolve_build_time(os.environ, lambda: datetime.now(UTC))


def purge_doc(app: Sphinx, env: BuildEnvironment, docname: str) -> None:
    del app
    cast(MaatlogDomain, env.get_domain("maatlog")).clear_doc(docname)


def merge_info(
    app: Sphinx,
    env: BuildEnvironment,
    docnames: Collection[str],
    other: BuildEnvironment,
) -> None:
    del app
    # Worker envs arrive pickled with domains=None; use domaindata, not get_domain().
    domain = cast(MaatlogDomain, env.get_domain("maatlog"))
    domain.merge(other.domaindata["maatlog"], docnames)


def finalize_domain(app: Sphinx, env: BuildEnvironment) -> None:
    domain = cast(MaatlogDomain, env.get_domain("maatlog"))
    build_time = cast(datetime, app.__dict__["_maatlog_build_time"])
    config = MaatlogConfig.from_sphinx(app.config)
    index = domain.finalize(
        config,
        build_time=build_time,
        known_docnames=set(env.found_docs),
    )
    # env.found_docs, the published index, and srcdir are all available only here,
    # so author profile cross-references are resolved once, at this point.
    resolved = ResolvedProfiles(avatars={})
    if config.author_profiles:
        resolved = resolve_profiles(
            config.author_profiles,
            authors=config.authors,
            index=index,
            known_docnames=set(env.found_docs),
            srcdir=Path(app.srcdir),
        )
        register_avatars(env, resolved.avatars, root=config.archive_docname)
        mark_about_documents_orphan(env, config.author_profiles)
    app.__dict__["_maatlog_resolved_profiles"] = resolved
    if config.home_docname is not None and config.home_docname not in env.found_docs:
        logger.warning(
            "maatlog_home_docname %r does not match any document; the blog home is disabled",
            config.home_docname,
            type="maatlog",
            subtype="home.docname-unknown",
            once=True,
        )


def inject_maatlog_page_context(
    app: Sphinx,
    pagename: str,
    templatename: str,
    context: dict[str, Any],
    doctree: nodes.document | None,
) -> str | None:
    """Always inject the stable ``maatlog`` namespace; override post/home templates when available.

    Non-post pages get :func:`normal_page_context` only when ``context["maatlog"]`` is
    not already set (so Plan 04 archive collectors can pre-seed archive context).
    The configured home docname (when it exists) gets :func:`home_context` before
    the post branch, so a document that is both home and a post renders as home.
    If that document is also a post, :func:`capture_internal_body` still runs so
    Atom feeds can read the fragment. Post pages always get :func:`build_post_context`
    with neighbors, taxonomies, absolute page／canonical URLs, and feed discovery
    links. Internal post body fragments are persisted to the build-local fragment
    store when feeds are on.
    Template override to ``maatlog/home.html`` or ``maatlog/post.html`` only happens
    when the selected theme can resolve that template. When the theme cannot resolve
    ``maatlog/home.html``, the configured home page renders as a normal page (with
    the ``maatlog.theme.home-template-missing`` warning) and the archive root's
    first page carries ``is_home`` instead.
    """
    del templatename, doctree
    config = MaatlogConfig.from_sphinx(app.config)
    site = _site_view(app, pagename, config)
    # Full HTML only: archives / theme post template / body store / feed discovery.
    if builder_capability(app.builder) is not BuilderCapability.FULL_HTML:
        context.setdefault("maatlog", as_template_mapping(empty_context(site=site)))
        return None

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    posts = cast(dict[str, Post], domain.data["posts_by_docname"])
    home_docname = resolved_home_docname(app, config)
    if home_docname is not None and pagename == home_docname:
        post = posts.get(pagename)
        if post is not None:
            capture_internal_body(app, pagename, post, context)
            if post.canonical_url is not None:
                context["pageurl"] = post.canonical_url
        index = cast(DomainIndex | None, domain.data.get("index"))
        published = index.published if index is not None else ()
        linker = post_taxonomy_linker(index, builder=app.builder, from_docname=pagename, root=config.archive_docname)
        context["maatlog"] = as_template_mapping(
            home_context(
                published,
                app.builder,
                docname=pagename,
                page_size=config.page_size,
                site=site,
                linker=linker.for_post,
                taxonomies=(
                    taxonomy_navigation(
                        index,
                        builder=app.builder,
                        from_docname=pagename,
                        root=config.archive_docname,
                    )
                    if index is not None
                    else None
                ),
                feeds=_archive_discovery_feeds(app, page_axis=None, taxonomy_id=None, label="Posts"),
                author_summaries=_author_summaries(app, from_docname=pagename, config=config, linker=linker),
            )
        )
        return HOME_TEMPLATE

    if (
        config.home_docname is not None
        and pagename == config.home_docname
        and config.home_docname in app.env.found_docs
        and not theme_can_resolve_template(app, HOME_TEMPLATE)
    ):
        logger.warning(
            "Theme cannot resolve %r; %r is rendered as a normal page without the post list",
            HOME_TEMPLATE,
            pagename,
            type="maatlog",
            subtype="theme.home-template-missing",
            once=True,
        )

    _apply_about_canonical(app, pagename, config, context)

    post = posts.get(pagename)

    if post is None:
        index = cast(DomainIndex | None, domain.data.get("index"))
        linker = post_taxonomy_linker(index, builder=app.builder, from_docname=pagename, root=config.archive_docname)
        if "maatlog" not in context:
            context["maatlog"] = as_template_mapping(
                normal_page_context(
                    site=site,
                    taxonomies=(
                        taxonomy_navigation(
                            index,
                            builder=app.builder,
                            from_docname=pagename,
                            root=config.archive_docname,
                        )
                        if index is not None
                        else None
                    ),
                    feeds=_archive_discovery_feeds(app, page_axis=None, taxonomy_id=None, label="Posts"),
                    author_summaries=_author_summaries(app, from_docname=pagename, config=config, linker=linker),
                )
            )
        return None

    body_html = capture_internal_body(app, pagename, post, context)
    index = cast(DomainIndex | None, domain.data.get("index"))
    published = index.published if index is not None else ()
    newer, older = neighbors(published, post.slug)
    linker = post_taxonomy_linker(index, builder=app.builder, from_docname=pagename, root=config.archive_docname)
    navigation = NavigationView(
        newer_post=_neighbor_card(app, pagename, newer, linker),
        older_post=_neighbor_card(app, pagename, older, linker),
    )
    taxonomies = (
        taxonomy_navigation(
            index,
            builder=app.builder,
            from_docname=pagename,
            root=config.archive_docname,
        )
        if index is not None
        else None
    )
    feeds = _post_discovery_feeds(app, post, config=config, index=index)
    page_url = absolute_doc_url(app, pagename)
    maattop_data = domain.maattop_for(pagename)
    top_image_url = image_url_for(app.builder, pagename, maattop_data["uri"]) if maattop_data else None
    top_image_alt = maattop_data["alt"] if maattop_data else ""
    maatlog_context = build_post_context(
        post,
        body_html=body_html,
        page_url=page_url,
        image_url=image_url_for(app.builder, pagename, post.image_uri),
        navigation=navigation,
        feeds=feeds,
        taxonomies=taxonomies,
        site=site,
        post_taxonomies=linker.for_post(post),
        top_image_url=top_image_url,
        top_image_alt=top_image_alt,
        author_summaries=_author_summaries(
            app, from_docname=pagename, config=config, linker=linker, author_ids=post.authors
        ),
    )
    context["maatlog"] = as_template_mapping(maatlog_context)
    # Suppress Sphinx basic-theme ``pageurl`` canonical; ``maatlog_head`` owns it
    # so explicit ``maatlog-canonical-url`` is not overridden by html_baseurl.
    context["pageurl"] = None
    if theme_can_resolve_template(app, POST_TEMPLATE):
        return POST_TEMPLATE
    return None


def collect_archive_pages(app: Sphinx) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Yield ``(pagename, context, template)`` for each projected archive page.

    Builds context via :func:`archive_context` without mutating domain data.
    Always includes the all-posts archive (even when empty).

    Only full HTML builders (``html`` / ``dirhtml``) collect archive pages.
    """
    if not is_full_html_builder(app.builder):
        return

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    index = cast(DomainIndex | None, domain.data.get("index"))
    if index is None:
        return

    config = MaatlogConfig.from_sphinx(app.config)
    pages = project_archives(
        index,
        root=config.archive_docname,
        page_size=config.page_size,
        timezone=config.timezone,
    )
    # Fail before yielding so Sphinx never writes colliding archive HTML.
    check_generated_docnames(
        tuple(page.docname for page in pages),
        known_docnames=set(app.env.found_docs),
    )
    home_docname = resolved_home_docname(app, config)
    for page in pages:
        taxonomies = taxonomy_navigation(
            index,
            builder=app.builder,
            from_docname=page.docname,
            root=config.archive_docname,
        )
        feeds = _archive_discovery_feeds(
            app, page_axis=page.key.axis, taxonomy_id=page.key.value, label=page.key.label
        )
        linker = post_taxonomy_linker(
            index, builder=app.builder, from_docname=page.docname, root=config.archive_docname
        )
        is_home = home_docname is None and page.key.axis is None and page.number == 1
        profile_view = _profile_view_for(app, page, index=index, config=config, linker=linker)
        # 著者アーカイブでは既定著者ではなくそのアーカイブの著者を出す。ページの主題と
        # 右ペインの内容が食い違うのを避ける。1 ページ目は page_kind="profile" なので
        # 右ペイン自体を出さず、ここに来るのは 2 ページ目以降だけである。
        archive_authors: tuple[str, ...] = ()
        if page.key.axis is TaxonomyAxis.AUTHOR and page.key.value is not None:
            archive_authors = (page.key.value,)
        summaries = (
            ()
            if profile_view is not None
            else _author_summaries(
                app,
                from_docname=page.docname,
                config=config,
                linker=linker,
                author_ids=archive_authors,
            )
        )
        maatlog = as_template_mapping(
            archive_context(
                page,
                app.builder,
                all_pages=pages,
                taxonomies=taxonomies,
                feeds=feeds,
                site=_site_view(app, page.docname, config),
                linker=linker.for_post,
                is_home=is_home,
                profile=profile_view,
                author_summaries=summaries,
            )
        )
        yield (
            page.docname,
            {
                "maatlog": maatlog,
                "title": page.key.label,
            },
            PROFILE_TEMPLATE if profile_view is not None else ARCHIVE_TEMPLATE,
        )


def _post_discovery_feeds(
    app: Sphinx,
    post: Post,
    *,
    config: MaatlogConfig,
    index: DomainIndex | None,
) -> tuple[FeedLinkView, ...]:
    if not discovery_feeds_enabled(app):
        return ()
    base = resolved_baseurl(app)
    if base is None:
        return ()
    project_title = str(getattr(app.config, "project", "") or "Project")
    return post_feed_links(
        post,
        baseurl=base,
        archive_root=config.archive_docname,
        project_title=project_title,
        feed_taxonomies=config.feed_taxonomies,
        index=index,
        timezone=config.timezone,
    )


def _author_summaries(
    app: Sphinx,
    *,
    from_docname: str,
    config: MaatlogConfig,
    linker: PostTaxonomyLinker,
    author_ids: Sequence[str] = (),
) -> tuple[AuthorSummaryView, ...]:
    """Summaries for the right rail of one page.

    *author_ids* is what the page itself knows about its authors: a post's
    ``:maatlog-authors:``, or the author an author archive belongs to. When it
    is empty the page cannot name an author, so the explicitly configured
    ``maatlog_default_author`` stands in. Nothing is chosen implicitly.
    """
    ids = tuple(author_ids)
    if not ids:
        ids = () if config.default_author is None else (config.default_author,)
    if not ids:
        return ()
    authors = linker.for_authors(ids)
    if config.authors is not None:
        authors = tuple(
            TaxonomyLinkView(
                id=author.id,
                label=config.authors.get(author.id, author.label),
                url=author.url,
            )
            for author in authors
        )
    return author_summary_views(
        app.builder,
        authors=authors,
        profiles=config.author_profiles or {},
        avatars=resolved_profiles(app).avatars,
        from_docname=from_docname,
    )


def _profile_view_for(
    app: Sphinx,
    page: ArchivePage,
    *,
    index: DomainIndex,
    config: MaatlogConfig,
    linker: PostTaxonomyLinker,
) -> AuthorProfileView | None:
    """Return the profile view for page 1 of a configured author, else ``None``.

    Page 2 and beyond stay plain author archives, so the profile header, About,
    Interests, Stats and Featured sections appear exactly once per author.
    """
    if page.key.axis is not TaxonomyAxis.AUTHOR or page.number != 1 or page.key.value is None:
        return None
    profiles = config.author_profiles or {}
    profile = profiles.get(page.key.value)
    if profile is None:
        return None
    return build_profile_view(
        app.builder,
        author_id=page.key.value,
        display_name=page.key.label,
        profile=profile,
        index=index,
        avatar_uri=resolved_profiles(app).avatars.get(page.key.value),
        from_docname=page.docname,
        timezone=config.timezone,
        linker=linker.for_post,
    )


def _archive_discovery_feeds(
    app: Sphinx,
    *,
    page_axis: TaxonomyAxis | None,
    taxonomy_id: str | None,
    label: str,
) -> tuple[FeedLinkView, ...]:
    if not discovery_feeds_enabled(app):
        return ()
    base = resolved_baseurl(app)
    if base is None:
        return ()
    config = MaatlogConfig.from_sphinx(app.config)
    project_title = str(getattr(app.config, "project", "") or "Project")
    return archive_feed_links(
        baseurl=base,
        archive_root=config.archive_docname,
        project_title=project_title,
        feed_taxonomies=config.feed_taxonomies,
        axis=page_axis,
        taxonomy_id=taxonomy_id,
        label=label,
    )


def _apply_about_canonical(app: Sphinx, pagename: str, config: MaatlogConfig, context: dict[str, Any]) -> None:
    """Point an About document's canonical URL at the profile page that embeds it.

    The same text is reachable from the About document's own URL and from the
    profile page. Consolidating on the profile page keeps the canonical honest
    without excluding the source document from the build.

    No-op without a resolved ``html_baseurl``: a relative canonical is invalid,
    and Sphinx itself emits none in that case.
    """
    profiles = config.author_profiles
    if not profiles or resolved_baseurl(app) is None:
        return
    for author_id, profile in profiles.items():
        if profile.about_docname == pagename:
            context["pageurl"] = absolute_doc_url(app, profile_docname(config.archive_docname, author_id))
            return


def _site_view(app: Sphinx, pagename: str, config: MaatlogConfig) -> SiteView:
    """Build the per-page ``maatlog.site`` view (archive URL is page-relative)."""
    return SiteView(
        title=str(getattr(app.config, "project", "") or ""),
        tagline=config.tagline,
        archive_url=relative_page_url_for(app.builder, pagename, config.archive_docname),
        top_image_title_font=config.top_image_title_font,
        content_width=config.content_width,
    )


def resolved_profiles(app: Sphinx) -> ResolvedProfiles:
    """Return the profile data resolved during ``env-updated``.

    Empty when no profile is configured or the build has not reached
    :func:`finalize_domain` yet (document-only builders never do).
    """
    value = app.__dict__.get("_maatlog_resolved_profiles")
    return value if isinstance(value, ResolvedProfiles) else ResolvedProfiles(avatars={})


def resolved_home_docname(app: Sphinx, config: MaatlogConfig) -> str | None:
    """Return the configured home docname when the site renders it as the blog top.

    ``None`` when home is not configured, the docname does not exist, or the
    selected theme cannot resolve ``maatlog/home.html``. In the last case the
    configured page falls back to a normal page (with the
    ``maatlog.theme.home-template-missing`` warning) and the archive root's
    first page carries ``is_home`` instead, so exactly one page in the site
    stays the blog top.
    """
    if config.home_docname is None:
        return None
    if config.home_docname not in app.env.found_docs:
        return None
    if not theme_can_resolve_template(app, HOME_TEMPLATE):
        return None
    return config.home_docname


def collect_post_lists(app: Sphinx, doctree: nodes.document) -> None:
    """Record docnames embedding ``post_list`` nodes for incremental rewrites.

    Runs on ``doctree-read``: unchanged documents are not re-read on
    incremental builds, so the domain keeps this set across builds until the
    document is purged (``clear_doc``) before its next read or replaced by a
    parallel worker merge.
    """
    if next(doctree.findall(post_list), None) is None:
        return
    docname = app.env.current_document.docname
    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    domain.note_post_list(docname)


def collect_maattop(app: Sphinx, doctree: nodes.document) -> None:
    """Remove ``maattop_node`` from doctree; store the first in the Domain.

    Runs on ``doctree-read`` at priority 102 (after collect_post_lists at 101).
    The first ``maattop_node`` is recorded in the domain; subsequent ones
    produce a warning and are discarded. All nodes are removed from the tree.
    """
    maattop_nodes = list(doctree.findall(maattop_node))
    if not maattop_nodes:
        return

    docname = app.env.current_document.docname
    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))

    first, *rest = maattop_nodes
    existing = domain.maattop_for(docname)
    if existing is not None:
        logger.warning(
            "Both maattop directive and maatlog-top-image front matter found in %r; the directive takes precedence.",
            docname,
            type="maatlog",
            subtype="maattop.duplicate",
        )
    domain.note_maattop(docname, uri=str(first["uri"]), alt=str(first.get("alt", "")))

    for duplicate in rest:
        logger.warning(
            "Multiple maattop directives found in %r; only the first is used.",
            docname,
            location=(duplicate.source, duplicate.line),
            type="maatlog",
            subtype="maattop.duplicate",
        )

    for node in maattop_nodes:
        node.parent.remove(node)


type ToctreeShape = tuple[tuple[tuple[str, str], ...], bool, int | None, str, bool]
type HtmlShellFingerprint = tuple[
    tuple[str, ...],
    tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[str, tuple[ToctreeShape, ...]], ...],
]

_HTML_SHELL_STATE_FILENAME = "maatlog_html_shell_fingerprints.pickle"


def _published_index_fingerprint(
    index: DomainIndex | None,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...]]:
    """Published slugs and taxonomy membership of a domain index (no titles)."""
    if index is None:
        return ((), ())
    slugs = tuple(post.slug for post in index.published)
    members = tuple(
        (
            axis.value,
            tuple(sorted((key, tuple(values)) for key, values in mapping.items())),
        )
        for axis, mapping in sorted(index.members.items(), key=lambda item: item[0].value)
    )
    return (slugs, members)


def _document_toctree_shapes(env: BuildEnvironment, docname: str) -> tuple[ToctreeShape, ...]:
    """Shape of every toctree in one document, in document order.

    Captures what ``nav-sidebar.html`` renders: each entry's explicit title
    (empty when the title is implicit) plus the referenced docname, whether
    the toctree is hidden, the depth and caption that shape the list, and
    whether ``includehidden`` on the node overrides the helper argument.
    Implicit titles stay empty so heading edits remain the job of ``env.titles``.
    """
    toc = env.tocs.get(docname)
    if toc is None:
        return ()
    return tuple(
        (
            tuple((title or "", reference) for title, reference in node["entries"]),
            bool(node.get("hidden", False)),
            node.get("maxdepth"),
            node.get("caption") or "",
            bool(node.get("includehidden", False)),
        )
        for node in toc.findall(addnodes.toctree)
    )


def _toctree_fingerprint(env: BuildEnvironment) -> tuple[tuple[str, tuple[ToctreeShape, ...]], ...]:
    """Site-wide toctree structure, so nav-only edits invalidate plain pages."""
    return tuple((docname, _document_toctree_shapes(env, docname)) for docname in sorted(env.found_docs))


def _html_shell_fingerprint(index: DomainIndex | None, env: BuildEnvironment) -> HtmlShellFingerprint:
    """Snapshot of what every plain page embeds: posts, taxonomies, titles, toctrees."""
    slugs, members = _published_index_fingerprint(index)
    titles = tuple(
        (docname, env.titles[docname].astext() if docname in env.titles else "") for docname in sorted(env.found_docs)
    )
    return (slugs, members, titles, _toctree_fingerprint(env))


def _html_shell_state_key(app: Sphinx) -> tuple[str, str]:
    return (app.builder.name, str(Path(app.outdir).resolve()))


def _html_shell_state_path(app: Sphinx) -> Path:
    return Path(app.doctreedir) / _HTML_SHELL_STATE_FILENAME


def _load_html_shell_fingerprints(app: Sphinx) -> dict[tuple[str, str], HtmlShellFingerprint]:
    """Load the sidecar state; a corrupt or unreadable file means "no state"."""
    path = _html_shell_state_path(app)
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            value = pickle.load(handle)
    except OSError, pickle.PickleError, AttributeError, EOFError, TypeError, ValueError:
        return {}
    return cast(dict[tuple[str, str], HtmlShellFingerprint], value) if isinstance(value, dict) else {}


def commit_html_shell_fingerprint(app: Sphinx, exception: Exception | None) -> None:
    """Persist the pending shell fingerprint only after a successful full HTML build."""
    if exception is not None or not is_full_html_builder(app.builder):
        return
    pending = cast(HtmlShellFingerprint | None, getattr(app, "_maatlog_pending_html_shell_fingerprint", None))
    if pending is None:
        return
    fingerprints = _load_html_shell_fingerprints(app)
    fingerprints[_html_shell_state_key(app)] = pending
    path = _html_shell_state_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(fingerprints, handle, pickle.HIGHEST_PROTOCOL)


def force_home_doc_updated(app: Sphinx, env: BuildEnvironment) -> list[str]:
    """Rewrite HTML that embeds the published index, without re-reading sources.

    Home and post pages always rewrite. Pages embedding ``maatlog:post-list``
    always rewrite too, because cards can change when excerpt or body changes
    without shifting slugs, membership, titles, or toctrees. Other found docs
    rewrite only when the HTML shell fingerprint — published slugs, taxonomy
    membership, document titles, and site-wide toctree structure — changed
    since the last successful full HTML build (compared per builder name and
    resolved output directory).
    """
    if not is_full_html_builder(app.builder):
        return []
    config = MaatlogConfig.from_sphinx(app.config)
    docnames: dict[str, None] = {}
    home_docname = resolved_home_docname(app, config)
    if home_docname is not None:
        docnames[home_docname] = None
    domain = cast(MaatlogDomain, env.get_domain("maatlog"))
    posts = cast(dict[str, Post], domain.data.get("posts_by_docname", {}))
    for docname in posts:
        docnames[docname] = None
    for docname in domain.post_list_docnames():
        docnames[docname] = None
    current = _html_shell_fingerprint(cast(DomainIndex | None, domain.data.get("index")), env)
    setattr(app, "_maatlog_pending_html_shell_fingerprint", current)  # noqa: B010 — dynamic attr on Sphinx, unknown to pyright
    previous = _load_html_shell_fingerprints(app).get(_html_shell_state_key(app))
    if current != previous:
        for docname in sorted(env.found_docs):
            docnames[docname] = None
    return list(docnames)


def _neighbor_card(
    app: Sphinx,
    from_docname: str,
    post: Post | None,
    linker: PostTaxonomyLinker | None = None,
) -> PostCardView | None:
    if post is None:
        return None
    return post_card_view(
        post,
        page_url=relative_page_url_for(app.builder, from_docname, post.docname),
        image_url=image_url_for(app.builder, from_docname, post.image_uri),
        taxonomies=linker.for_post(post) if linker is not None else None,
    )


def finalize_generated_outputs(app: Sphinx, exception: Exception | None) -> None:
    """Commit page ownership, write feeds, then always remove the body fragment store."""
    output_failed = False
    try:
        commit_page_outputs(app, exception)
        write_feeds_after_success(app, exception)
    except BaseException:
        output_failed = True
        raise
    finally:
        try:
            cleanup_body_fragment_store(app)
        except MaatlogBuildError as cleanup_error:
            if exception is not None or output_failed:
                logger.warning("%s", cleanup_error, type="maatlog", subtype="feed.cleanup-failed")
            else:
                raise


def _visit_maattop(self: Any, node: maattop_node) -> None:  # type: ignore[type-arg]
    raise nodes.SkipNode


def setup(app: Sphinx) -> ExtensionMetadata:
    app.require_sphinx("9.1")
    app.setup_extension("myst_parser")
    app.add_domain(MaatlogDomain)
    app.add_node(
        post_list,
        html=(html_visit_post_list, html_depart_post_list),
        latex=(latex_visit_post_list, None),
        text=(text_visit_post_list, None),
        man=(text_visit_post_list, None),
        texinfo=(text_visit_post_list, None),
    )
    app.add_node(
        maattop_node,
        html=(_visit_maattop, None),
        latex=(_visit_maattop, None),
        text=(_visit_maattop, None),
        man=(_visit_maattop, None),
        texinfo=(_visit_maattop, None),
    )
    register_config(app)
    _register_bundled_themes(app)
    app.connect("config-inited", initialize_build_time)
    app.connect("builder-inited", warn_partial_support_once)
    # Filters must exist before theme template compilation in validate_selected_theme.
    app.connect("builder-inited", _initialize_html_metadata)
    app.connect("builder-inited", validate_selected_theme)
    app.connect("builder-inited", link_palette_stylesheet)
    app.connect("builder-inited", apply_pygments_style)
    app.connect("source-read", capture_source, priority=999)
    app.connect("doctree-read", collect_maattop_from_myst, priority=99)
    app.connect("doctree-read", collect_post, priority=100)
    app.connect("doctree-read", collect_post_lists, priority=101)
    app.connect("doctree-read", collect_maattop, priority=102)
    app.connect("env-get-outdated", force_post_docs_outdated_for_feeds)
    app.connect("env-purge-doc", purge_doc)
    app.connect("env-merge-info", merge_info)
    app.connect("env-updated", finalize_domain)
    app.connect("env-get-updated", force_home_doc_updated)
    app.connect("doctree-resolved", process_post_list_nodes)
    app.connect("html-collect-pages", collect_archive_pages)
    app.connect("html-page-context", inject_maatlog_page_context)
    app.connect("write-started", prepare_body_fragment_store)
    app.connect("write-started", register_representative_images)
    # Pages then feeds, then fragment-store cleanup (always).
    app.connect("build-finished", finalize_generated_outputs)
    app.connect("build-finished", cleanup_sources)
    # Shell refresh state commits last; never on a failed build.
    app.connect("build-finished", commit_html_shell_fingerprint)
    return {
        "version": PACKAGE_VERSION,
        # 3: the domain now tracks ``maattop_by_docname``. Environments
        # pickled before the key existed would leave maattop pages stale,
        # so force one full rebuild to repopulate the tracking set.
        "env_version": 3,
        "parallel_read_safe": True,
        # parallel_write_safe: archive HTML is produced only via main-process
        # html-collect-pages (Sphinx write/finish), not worker writers.
        # Page/feed ownership manifests and Atom files are written only from
        # build-finished (finalize_generated_outputs). Body fragments use a
        # doctreedir-backed store shared across parallel writers.
        "parallel_write_safe": True,
    }


def _initialize_html_metadata(app: Sphinx) -> None:
    """Validate／cache html_baseurl for the current builder.

    Full HTML only; document-only and partial builders never require
    ``html_baseurl``. Body fragments are prepared later on ``write-started``.
    """
    if not is_full_html_builder(app.builder):
        return
    ensure_feed_baseurl(app)
    _register_template_filters(app)


def maatlog_json(values: Iterable[object]) -> str:
    """Return a compact JSON array for HTML data attributes (ASCII-safe)."""
    return json.dumps(list(values), ensure_ascii=True, separators=(",", ":"))


def _register_template_filters(app: Sphinx) -> None:
    templates = getattr(app.builder, "templates", None)
    if templates is None:
        return
    environment = getattr(templates, "environment", None)
    if environment is None:
        return
    config = MaatlogConfig.from_sphinx(app.config)
    timezone = config.timezone

    def maatlog_post_date(value: datetime) -> str:
        return format_post_date(value, timezone)

    environment.filters["maatlog_post_date"] = maatlog_post_date
    environment.filters["maatlog_json"] = maatlog_json

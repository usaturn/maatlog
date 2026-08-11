import os
from collections.abc import Collection, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.config import Config
from sphinx.environment import BuildEnvironment
from sphinx.util import logging
from sphinx.util.typing import ExtensionMetadata

from .archives import check_generated_docnames, project_archives
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
    post_feed_links,
    prepare_body_fragment_store,
    resolved_baseurl,
)
from .metadata import capture_source, cleanup_sources, collect_post
from .model import Post
from .navigation import neighbors, taxonomy_navigation
from .outputs import commit_page_outputs
from .taxonomy import DomainIndex
from .theme_api import validate_selected_theme
from .version import PACKAGE_VERSION
from .views import (
    FeedLinkView,
    NavigationView,
    PostCardView,
    archive_context,
    as_template_mapping,
    build_post_context,
    empty_context,
    image_url_for,
    post_card_view,
    register_representative_images,
    relative_page_url_for,
    theme_can_resolve_template,
)

logger = logging.getLogger(__name__)

POST_TEMPLATE = "maatlog/post.html"
ARCHIVE_TEMPLATE = "maatlog/archive.html"
_THEMES_DIR = Path(__file__).resolve().parent / "themes"


def _register_bundled_themes(app: Sphinx) -> None:
    """Register official MaatLog HTML themes shipped as package data."""
    for name in ("maatlog-base", "maatlog-default"):
        path = _THEMES_DIR / name
        if path.is_dir():
            app.add_html_theme(name, str(path))


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
    domain.finalize(
        MaatlogConfig.from_sphinx(app.config),
        build_time=build_time,
        known_docnames=set(env.found_docs),
    )


def inject_maatlog_page_context(
    app: Sphinx,
    pagename: str,
    templatename: str,
    context: dict[str, Any],
    doctree: nodes.document | None,
) -> str | None:
    """Always inject the stable ``maatlog`` namespace; override post template when available.

    Non-post pages get :func:`empty_context` only when ``context["maatlog"]`` is
    not already set (so Plan 04 archive collectors can pre-seed archive context).
    Post pages always get :func:`build_post_context` with neighbors, taxonomies,
    absolute page／canonical URLs, and feed discovery links. Internal post body
    fragments are persisted to the build-local fragment store when feeds are on.
    Template override to ``maatlog/post.html`` only happens when the selected theme
    can resolve that template.
    """
    del templatename, doctree
    # Full HTML only: archives / theme post template / body store / feed discovery.
    if builder_capability(app.builder) is not BuilderCapability.FULL_HTML:
        context.setdefault("maatlog", as_template_mapping(empty_context()))
        return None

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    posts = cast(dict[str, Post], domain.data["posts_by_docname"])
    post = posts.get(pagename)

    if post is None:
        context.setdefault("maatlog", as_template_mapping(empty_context()))
        return None

    body_html = capture_internal_body(app, pagename, post, context)
    config = MaatlogConfig.from_sphinx(app.config)
    index = cast(DomainIndex | None, domain.data.get("index"))
    published = index.published if index is not None else ()
    newer, older = neighbors(published, post.slug)
    navigation = NavigationView(
        newer_post=_neighbor_card(app, pagename, newer),
        older_post=_neighbor_card(app, pagename, older),
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
    maatlog_context = build_post_context(
        post,
        body_html=body_html,
        page_url=page_url,
        image_url=image_url_for(app.builder, pagename, post.image_uri),
        navigation=navigation,
        feeds=feeds,
        taxonomies=taxonomies,
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
        maatlog = as_template_mapping(
            archive_context(
                page,
                app.builder,
                all_pages=pages,
                taxonomies=taxonomies,
                feeds=feeds,
            )
        )
        yield (
            page.docname,
            {
                "maatlog": maatlog,
                "title": page.key.label,
            },
            ARCHIVE_TEMPLATE,
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


def _neighbor_card(app: Sphinx, from_docname: str, post: Post | None) -> PostCardView | None:
    if post is None:
        return None
    return post_card_view(
        post,
        page_url=relative_page_url_for(app.builder, from_docname, post.docname),
        image_url=image_url_for(app.builder, from_docname, post.image_uri),
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
    register_config(app)
    _register_bundled_themes(app)
    app.connect("config-inited", initialize_build_time)
    app.connect("builder-inited", warn_partial_support_once)
    app.connect("builder-inited", validate_selected_theme)
    app.connect("builder-inited", _initialize_html_metadata)
    app.connect("source-read", capture_source, priority=999)
    app.connect("doctree-read", collect_post, priority=100)
    app.connect("env-get-outdated", force_post_docs_outdated_for_feeds)
    app.connect("env-purge-doc", purge_doc)
    app.connect("env-merge-info", merge_info)
    app.connect("env-updated", finalize_domain)
    app.connect("doctree-resolved", process_post_list_nodes)
    app.connect("html-collect-pages", collect_archive_pages)
    app.connect("html-page-context", inject_maatlog_page_context)
    app.connect("write-started", prepare_body_fragment_store)
    app.connect("write-started", register_representative_images)
    # Pages then feeds, then fragment-store cleanup (always).
    app.connect("build-finished", finalize_generated_outputs)
    app.connect("build-finished", cleanup_sources)
    return {
        "version": PACKAGE_VERSION,
        "env_version": 1,
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

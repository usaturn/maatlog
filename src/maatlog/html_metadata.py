"""Build-local HTML body fragment store, absolute post URLs, and feed discovery links."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence, Set
from pathlib import Path
from typing import Any, Final, cast
from zoneinfo import ZoneInfo

from sphinx.application import Sphinx
from sphinx.builders import Builder
from sphinx.environment import BuildEnvironment

from .builders import is_full_html_builder
from .config import MaatlogConfig, TaxonomyAxis
from .errors import Diagnostic, MaatlogBuildError
from .feeds import feed_title
from .model import Post
from .taxonomy import DomainIndex
from .urls import absolute_page_url, validate_baseurl
from .views import FeedLinkView, page_url_for

_BASEURL_ATTR = "_maatlog_baseurl"

BODY_FRAGMENT_DIRNAME: Final[str] = "maatlog_body_fragments"


def _body_fragment_dir(app: Sphinx) -> Path:
    return Path(app.doctreedir) / BODY_FRAGMENT_DIRNAME


def _body_fragment_digest(docname: str) -> str:
    return hashlib.sha256(docname.encode("utf-8")).hexdigest()


def _body_fragment_path(app: Sphinx, docname: str) -> Path:
    return _body_fragment_dir(app) / f"{_body_fragment_digest(docname)}.json"


def _body_fragment_error(message: str, docname: str, value: str) -> MaatlogBuildError:
    return MaatlogBuildError(
        [
            Diagnostic(
                code="maatlog.feed.render-failed",
                message=message,
                field="body_html",
                value=value,
                expected=f"one valid rendered body record for internal post {docname!r}",
            )
        ]
    )


def prepare_body_fragment_store(app: Sphinx, builder: Builder) -> None:
    del builder
    if not discovery_feeds_enabled(app):
        return
    root = _body_fragment_dir(app)
    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise _body_fragment_error("Failed to reset rendered body store", "*", type(exc).__name__) from exc
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise _body_fragment_error("Failed to create rendered body store", "*", type(exc).__name__) from exc


def write_body_fragment(app: Sphinx, docname: str, body_html: str) -> None:
    root = _body_fragment_dir(app)
    target = _body_fragment_path(app, docname)
    try:
        fd, temp_name = tempfile.mkstemp(dir=root, prefix=f".{target.stem}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"docname": docname, "body_html": body_html}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError) as exc:
        raise _body_fragment_error("Failed to store rendered post body", docname, type(exc).__name__) from exc


def read_body_fragment(app: Sphinx, docname: str) -> str:
    target = _body_fragment_path(app, docname)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _body_fragment_error("Rendered post body is missing or unreadable", docname, type(exc).__name__) from exc
    if not isinstance(raw, dict):
        raise _body_fragment_error("Rendered post body record is invalid", docname, repr(raw))
    record = cast(dict[str, object], raw)
    body_html = record.get("body_html")
    if record.get("docname") != docname or not isinstance(body_html, str):
        raise _body_fragment_error("Rendered post body record is invalid", docname, repr(record))
    return body_html


def cleanup_body_fragment_store(app: Sphinx) -> None:
    try:
        shutil.rmtree(_body_fragment_dir(app))
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _body_fragment_error("Failed to remove rendered body store", "*", type(exc).__name__) from exc


def ensure_feed_baseurl(app: Sphinx) -> str | None:
    """Validate ``html_baseurl`` when feeds are enabled on a full HTML builder.

    Stores the normalized base URL on the application for later absolute URL
    resolution. When feeds are disabled, returns a validated base URL only if
    ``html_baseurl`` is present and valid; otherwise ``None`` (relative URIs).

    Document-only and partial HTML builders never require baseurl and clear any
    cached value (feeds and HTML metadata injection are disabled for them).
    """
    config = MaatlogConfig.from_sphinx(app.config)
    raw = getattr(app.config, "html_baseurl", None)
    raw_str = raw if isinstance(raw, str) else None

    if not is_full_html_builder(app.builder):
        app.__dict__[_BASEURL_ATTR] = None
        return None

    if config.generate_feeds:
        base = validate_baseurl(raw_str)
        app.__dict__[_BASEURL_ATTR] = base
        return base

    if raw_str and raw_str.strip():
        try:
            base = validate_baseurl(raw_str)
        except MaatlogBuildError:
            base = None
        app.__dict__[_BASEURL_ATTR] = base
        return base

    app.__dict__[_BASEURL_ATTR] = None
    return None


def resolved_baseurl(app: Sphinx) -> str | None:
    """Return the build-local normalized base URL, if any."""
    value = app.__dict__.get(_BASEURL_ATTR)
    return value if isinstance(value, str) else None


def capture_internal_body(app: Sphinx, pagename: str, post: Post, context: dict[str, Any]) -> str | None:
    """Cache and return the rendered body for internal posts only.

    External posts never store source body fragments for feeds or the template
    view. Returns the fragment string for internal posts, else ``None``.

    Body capture is a full-HTML concern (feeds / Theme API); other builders
    skip the store and return any available body without persisting it.
    """
    body = context.get("body")
    body_html = body if isinstance(body, str) else None
    if post.external_url is not None:
        return None
    if not is_full_html_builder(app.builder):
        return body_html
    if body_html is not None and discovery_feeds_enabled(app):
        write_body_fragment(app, pagename, body_html)
    return body_html


def force_post_docs_outdated_for_feeds(
    app: Sphinx,
    env: BuildEnvironment,
    added: Set[str],
    changed: Set[str],
    removed: Set[str],
) -> list[str]:
    """Mark all MaatLog post sources outdated when Atom feeds need body fragments.

    Body fragments are filled only in ``html-page-context`` for pages written
    this build. On incremental builds, unchanged posts would otherwise skip
    rewrite and leave the build-local fragment store incomplete.
    Forcing post docnames through ``env-get-outdated`` re-reads and rewrites
    them so feed generation always sees every internal body.

    No-op when feeds are disabled or the builder is not HTML.
    """
    del added, changed, removed
    if not discovery_feeds_enabled(app):
        return []
    domain = env.get_domain("maatlog")
    posts = cast(dict[str, Post], domain.data.get("posts_by_docname", {}))
    return sorted(posts)


def absolute_doc_url(app: Sphinx, docname: str) -> str:
    """Absolute page URL when baseurl is known; otherwise the builder URI."""
    uri = page_url_for(app.builder, docname)
    base = resolved_baseurl(app)
    if base is None:
        return uri
    return absolute_page_url(base, uri)


def feed_relative_path(
    archive_root: str,
    axis: TaxonomyAxis | None = None,
    key: str | None = None,
) -> str:
    """Relative output path for a MaatLog Atom feed under the HTML outdir."""
    if axis is None:
        return f"{archive_root}/atom.xml"
    if key is None:
        msg = "key is required when axis is set"
        raise ValueError(msg)
    return f"{archive_root}/{axis.value}/{key}/atom.xml"


def feed_absolute_url(
    baseurl: str, archive_root: str, axis: TaxonomyAxis | None = None, key: str | None = None
) -> str:
    """Absolute URL for a feed path joined with *baseurl*."""
    return absolute_page_url(baseurl, feed_relative_path(archive_root, axis, key))


def post_feed_links(
    post: Post,
    *,
    baseurl: str,
    archive_root: str,
    project_title: str,
    feed_taxonomies: Sequence[TaxonomyAxis],
    index: DomainIndex | None,
    timezone: ZoneInfo,
) -> tuple[FeedLinkView, ...]:
    """Discovery links: site feed plus taxonomy feeds the post belongs to.

    Only axes listed in *feed_taxonomies* are considered. Taxonomy feeds require
    at least one published member (always true for axes present on *post* when
    *post* itself is published).
    """
    links: list[FeedLinkView] = [
        FeedLinkView(
            title=feed_title(project_title),
            url=feed_absolute_url(baseurl, archive_root),
        )
    ]
    labels: Mapping[TaxonomyAxis, Mapping[str, str]] = index.labels if index is not None else {}
    for axis in feed_taxonomies:
        for taxonomy_id, label in _post_taxonomy_entries(post, axis, labels=labels, timezone=timezone):
            links.append(
                FeedLinkView(
                    title=feed_title(project_title, label),
                    url=feed_absolute_url(baseurl, archive_root, axis, taxonomy_id),
                )
            )
    return tuple(links)


def archive_feed_links(
    *,
    baseurl: str,
    archive_root: str,
    project_title: str,
    feed_taxonomies: Sequence[TaxonomyAxis],
    axis: TaxonomyAxis | None,
    taxonomy_id: str | None,
    label: str | None,
) -> tuple[FeedLinkView, ...]:
    """Discovery links for an archive page (site feed + this taxonomy feed)."""
    links: list[FeedLinkView] = [
        FeedLinkView(
            title=feed_title(project_title),
            url=feed_absolute_url(baseurl, archive_root),
        )
    ]
    if axis is not None and taxonomy_id is not None and axis in feed_taxonomies and label is not None:
        links.append(
            FeedLinkView(
                title=feed_title(project_title, label),
                url=feed_absolute_url(baseurl, archive_root, axis, taxonomy_id),
            )
        )
    return tuple(links)


def discovery_feeds_enabled(app: Sphinx) -> bool:
    """True when feed auto-discovery should be emitted (full HTML + generate_feeds)."""
    if not is_full_html_builder(app.builder):
        return False
    return MaatlogConfig.from_sphinx(app.config).generate_feeds


def _post_taxonomy_entries(
    post: Post,
    axis: TaxonomyAxis,
    *,
    labels: Mapping[TaxonomyAxis, Mapping[str, str]],
    timezone: ZoneInfo,
) -> list[tuple[str, str]]:
    axis_labels = dict(labels.get(axis, {}))

    if axis is TaxonomyAxis.TAG:
        ids = post.tags
    elif axis is TaxonomyAxis.CATEGORY:
        ids = post.categories
    elif axis is TaxonomyAxis.AUTHOR:
        ids = post.authors
    elif axis is TaxonomyAxis.MONTH:
        if post.published_at is None:
            return []
        month = post.published_at.astimezone(timezone).strftime("%Y-%m")
        return [(month, axis_labels.get(month, month))]
    else:
        return []

    return [(taxonomy_id, axis_labels.get(taxonomy_id, taxonomy_id)) for taxonomy_id in ids]

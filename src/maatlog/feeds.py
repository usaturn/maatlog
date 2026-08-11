"""Immutable Atom feed projection, deterministic XML, and feed file writing."""

from __future__ import annotations

import html
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import cast
from xml.etree.ElementTree import Element, SubElement, fromstring, register_namespace, tostring

from sphinx.application import Sphinx

from .config import MaatlogConfig, TaxonomyAxis
from .domain import MaatlogDomain
from .errors import Diagnostic, MaatlogBuildError
from .model import Post
from .references import archive_docname, is_html_archive_builder
from .taxonomy import DomainIndex
from .urls import PostUrls, absolutize_fragment_urls, post_urls
from .version import PACKAGE_VERSION

ATOM = "http://www.w3.org/2005/Atom"
DEFAULT_GENERATOR = f"MaatLog {PACKAGE_VERSION}"

_LINK_SELF = ("self", "application/atom+xml")
_LINK_ALTERNATE_HTML = ("alternate", "text/html")


@dataclass(frozen=True, slots=True)
class AtomCategory:
    term: str
    label: str
    scheme: str


@dataclass(frozen=True, slots=True)
class AtomEntry:
    identifier: str
    title: str
    published: datetime
    alternate_url: str
    related_url: str | None
    authors: tuple[str, ...]
    categories: tuple[AtomCategory, ...]
    summary: str | None
    content_html: str


@dataclass(frozen=True, slots=True)
class AtomFeed:
    identifier: str
    title: str
    updated: datetime
    self_url: str
    alternate_url: str
    author: str
    generator: str
    entries: tuple[AtomEntry, ...]


def feed_title(project_title: str, taxonomy_label: str | None = None) -> str:
    """Build a feed title; taxonomy feeds append `` — label``."""
    if taxonomy_label is None:
        return project_title
    return f"{project_title} — {taxonomy_label}"


def feed_author(project_author: str | None, project_title: str) -> str:
    """Resolve feed-level author: Sphinx ``author`` if non-empty, else project title."""
    if isinstance(project_author, str) and project_author.strip():
        return project_author.strip()
    return project_title


def default_generator() -> str:
    """Return ``MaatLog <version>`` for the Atom generator element."""
    return DEFAULT_GENERATOR


def atom_categories(
    tags: Sequence[str],
    categories: Sequence[str],
    *,
    tag_labels: Mapping[str, str] | None = None,
    category_labels: Mapping[str, str] | None = None,
) -> tuple[AtomCategory, ...]:
    """Project tag／category IDs into Atom categories (tags first, then categories)."""
    result: list[AtomCategory] = []
    tag_map = tag_labels or {}
    category_map = category_labels or {}
    for term in tags:
        result.append(
            AtomCategory(
                term=term,
                label=tag_map.get(term, term),
                scheme="urn:maatlog:tag",
            )
        )
    for term in categories:
        result.append(
            AtomCategory(
                term=term,
                label=category_map.get(term, term),
                scheme="urn:maatlog:category",
            )
        )
    return tuple(result)


def atom_entry(
    post: Post,
    *,
    urls: PostUrls,
    body_html: str | None = None,
    tag_labels: Mapping[str, str] | None = None,
    category_labels: Mapping[str, str] | None = None,
    author_labels: Mapping[str, str] | None = None,
) -> AtomEntry:
    """Project a published post into an :class:`AtomEntry`.

    External posts use excerpt HTML as content and set ``related_url`` to the
    MaatLog page URL; source ``body_html`` is never used. Internal posts use the
    provided body fragment with relative ``href``／``src`` absolutized against
    ``urls.page_url``.

    Taxonomy IDs in *post.authors* are mapped to display names via
    *author_labels* (defaulting to the ID when missing), matching tag／category
    label handling.
    """
    if post.published_at is None:
        msg = "atom entries require a published_at datetime"
        raise ValueError(msg)

    is_external = urls.external_url is not None
    if is_external:
        content_html = _excerpt_as_html(post.excerpt)
        related_url: str | None = urls.page_url
    else:
        raw = body_html or ""
        content_html = absolutize_fragment_urls(raw, urls.page_url) if raw else ""
        related_url = None

    author_map = author_labels or {}
    authors = tuple(author_map.get(author_id, author_id) for author_id in post.authors)

    return AtomEntry(
        identifier=urls.canonical_url,
        title=post.title,
        published=post.published_at,
        alternate_url=urls.primary_url,
        related_url=related_url,
        authors=authors,
        categories=atom_categories(
            post.tags,
            post.categories,
            tag_labels=tag_labels,
            category_labels=category_labels,
        ),
        summary=post.excerpt,
        content_html=content_html,
    )


def atom_feed(
    *,
    identifier: str,
    title: str,
    self_url: str,
    alternate_url: str,
    author: str,
    entries: Sequence[AtomEntry] = (),
    build_time: datetime,
    generator: str | None = None,
    limit: int | None = None,
) -> AtomFeed:
    """Build an :class:`AtomFeed` from ordered entries.

    *entries* must already be in published sequence order. *limit* truncates
    that sequence (``maatlog_feed_limit``). *updated* is the newest remaining
    entry's ``published``, or *build_time* when empty.
    """
    selected = tuple(entries)
    if limit is not None:
        selected = selected[:limit]
    if selected:
        updated = max(entry.published for entry in selected)
    else:
        updated = build_time
    return AtomFeed(
        identifier=identifier,
        title=title,
        updated=updated,
        self_url=self_url,
        alternate_url=alternate_url,
        author=author,
        generator=generator if generator is not None else default_generator(),
        entries=selected,
    )


def serialize_atom(feed: AtomFeed) -> bytes:
    """Serialize *feed* to UTF-8 Atom XML with a declaration.

    Attribute and child element order are fixed for byte-identical output given
    the same input values. Datetimes keep their original offset (RFC 3339);
    microseconds appear only when non-zero on the input value.
    """
    register_namespace("", ATOM)
    root = Element(_tag("feed"))

    _text_child(root, "id", feed.identifier)
    _text_child(root, "title", feed.title)
    _text_child(root, "updated", _rfc3339(feed.updated))
    _link(root, href=feed.self_url, rel=_LINK_SELF[0], type_=_LINK_SELF[1])
    _link(root, href=feed.alternate_url, rel=_LINK_ALTERNATE_HTML[0], type_=_LINK_ALTERNATE_HTML[1])
    _text_child(root, "generator", feed.generator)
    author_el = SubElement(root, _tag("author"))
    _text_child(author_el, "name", feed.author)

    for entry in feed.entries:
        entry_el = SubElement(root, _tag("entry"))
        _text_child(entry_el, "id", entry.identifier)
        _text_child(entry_el, "title", entry.title)
        _text_child(entry_el, "published", _rfc3339(entry.published))
        _text_child(entry_el, "updated", _rfc3339(entry.published))
        _link(entry_el, href=entry.alternate_url, rel="alternate")
        if entry.related_url is not None:
            _link(entry_el, href=entry.related_url, rel="related")
        for name in entry.authors:
            author_el = SubElement(entry_el, _tag("author"))
            _text_child(author_el, "name", name)
        for category in entry.categories:
            cat_el = SubElement(entry_el, _tag("category"))
            # Fixed attribute insertion order: term, label, scheme.
            cat_el.set("term", category.term)
            cat_el.set("label", category.label)
            cat_el.set("scheme", category.scheme)
        if entry.summary is not None:
            summary_el = SubElement(entry_el, _tag("summary"))
            summary_el.set("type", "text")
            summary_el.text = entry.summary
        content_el = SubElement(entry_el, _tag("content"))
        content_el.set("type", "html")
        content_el.text = entry.content_html

    return tostring(root, encoding="utf-8", xml_declaration=True)


def _tag(local: str) -> str:
    return f"{{{ATOM}}}{local}"


def _text_child(parent: Element, local: str, text: str) -> Element:
    element = SubElement(parent, _tag(local))
    element.text = text
    return element


def _link(
    parent: Element,
    *,
    href: str,
    rel: str,
    type_: str | None = None,
) -> Element:
    element = SubElement(parent, _tag("link"))
    # Fixed attribute insertion order: href, rel, type.
    element.set("href", href)
    element.set("rel", rel)
    if type_ is not None:
        element.set("type", type_)
    return element


def _rfc3339(value: datetime) -> str:
    """Format *value* as RFC 3339 without forcing UTC or dropping offset."""
    if value.tzinfo is None:
        msg = "Atom datetimes must be timezone-aware"
        raise ValueError(msg)
    return value.isoformat()


def _excerpt_as_html(excerpt: str | None) -> str:
    """Wrap excerpt text in a single HTML paragraph (escaped once for HTML)."""
    if not excerpt:
        return ""
    return f"<p>{html.escape(excerpt, quote=False)}</p>"


@dataclass(frozen=True, slots=True)
class FeedProjection:
    """One Atom feed ready to serialize to an outdir-relative path."""

    relative_path: str
    feed: AtomFeed


def project_feeds(domain: MaatlogDomain, app: Sphinx) -> tuple[FeedProjection, ...]:
    """Project overall and taxonomy Atom feeds for the current domain index.

    The overall feed is always included (possibly empty). Taxonomy feeds are
    emitted only for axes in ``maatlog_feed_taxonomies`` that have at least one
    published member.
    """
    # Local imports avoid a cycle with html_metadata (which imports feed_title).
    from .html_metadata import (
        absolute_doc_url,
        feed_absolute_url,
        feed_relative_path,
        read_body_fragment,
        resolved_baseurl,
    )

    index = cast(DomainIndex | None, domain.data.get("index"))
    if index is None:
        return ()

    config = MaatlogConfig.from_sphinx(app.config)
    baseurl = resolved_baseurl(app)
    if baseurl is None:
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.feed.baseurl-required",
                    message="html_baseurl is required for feed generation",
                    field="html_baseurl",
                    value="",
                    expected="an absolute HTTP or HTTPS URL with a host and without userinfo, query, or fragment",
                )
            ]
        )

    project_title = str(getattr(app.config, "project", "") or "Project")
    project_author = getattr(app.config, "author", None)
    author = feed_author(project_author if isinstance(project_author, str) else None, project_title)
    build_time = cast(datetime, app.__dict__["_maatlog_build_time"])
    tag_labels = index.labels.get(TaxonomyAxis.TAG, {})
    category_labels = index.labels.get(TaxonomyAxis.CATEGORY, {})
    author_labels = index.labels.get(TaxonomyAxis.AUTHOR, {})

    def entries_for(posts: Sequence[Post]) -> tuple[AtomEntry, ...]:
        return tuple(
            _atom_entry_for_post(
                app,
                post,
                tag_labels=tag_labels,
                category_labels=category_labels,
                author_labels=author_labels,
                body_html=None if post.external_url is not None else read_body_fragment(app, post.docname),
            )
            for post in posts
        )

    projections: list[FeedProjection] = []

    # Overall feed — always, even with zero published posts.
    overall_path = feed_relative_path(config.archive_docname)
    overall_self = feed_absolute_url(baseurl, config.archive_docname)
    overall_alternate = absolute_doc_url(app, config.archive_docname)
    projections.append(
        FeedProjection(
            relative_path=overall_path,
            feed=atom_feed(
                identifier=overall_self,
                title=feed_title(project_title),
                self_url=overall_self,
                alternate_url=overall_alternate,
                author=author,
                entries=entries_for(index.published),
                build_time=build_time,
                limit=config.feed_limit,
            ),
        )
    )

    posts_by_slug = {post.slug: post for post in index.published}
    for axis in config.feed_taxonomies:
        members = index.members.get(axis, {})
        labels = index.labels.get(axis, {})
        for taxonomy_id, slugs in members.items():
            if not slugs:
                continue
            # DomainIndex.members preserves the order established by index.published.
            ordered = tuple(posts_by_slug[slug] for slug in slugs if slug in posts_by_slug)
            if not ordered:
                continue
            label = labels.get(taxonomy_id, taxonomy_id)
            rel = feed_relative_path(config.archive_docname, axis, taxonomy_id)
            self_url = feed_absolute_url(baseurl, config.archive_docname, axis, taxonomy_id)
            archive = archive_docname(config.archive_docname, axis, taxonomy_id, page=1)
            alternate = absolute_doc_url(app, archive)
            projections.append(
                FeedProjection(
                    relative_path=rel,
                    feed=atom_feed(
                        identifier=self_url,
                        title=feed_title(project_title, label),
                        self_url=self_url,
                        alternate_url=alternate,
                        author=author,
                        entries=entries_for(ordered),
                        build_time=build_time,
                        limit=config.feed_limit,
                    ),
                )
            )

    return tuple(projections)


def write_feeds_after_success(app: Sphinx, exception: Exception | None) -> None:
    """Stage, validate, and atomically install Atom feeds after a successful HTML build.

    On success with feeds enabled: write all feeds, remove stale owned feed paths,
    and update only ``generated_outputs["feeds"]``. On success with feeds disabled:
    remove previously owned feeds and clear the feeds manifest. Never mutates the
    pages owner set. Failures raise :class:`MaatlogBuildError` before replacing
    existing feed files or updating the feeds manifest.
    """
    from .html_metadata import discovery_feeds_enabled
    from .outputs import get_owned_paths, load_persisted_outputs

    if exception is not None:
        return
    if not is_html_archive_builder(app.builder):
        return

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    doctreedir = Path(app.doctreedir)
    outdir = Path(app.outdir)
    persisted = load_persisted_outputs(doctreedir)
    previous = set(persisted["feeds"]) | get_owned_paths(domain, "feeds")

    if not discovery_feeds_enabled(app):
        _commit_feed_paths(app, domain, previous=previous, current=frozenset())
        return

    try:
        projections = project_feeds(domain, app)
        serialized = [(item.relative_path, serialize_atom(item.feed)) for item in projections]
        staged = _stage_all_xml(outdir, serialized)
        _validate_all_xml(staged)
        _replace_all(staged)
    except MaatlogBuildError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as feed render failure
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.feed.render-failed",
                    message=f"Failed to generate Atom feeds: {exc}",
                    field="feeds",
                    value=type(exc).__name__,
                    expected="successful Atom projection, XML serialization, and atomic write",
                )
            ]
        ) from exc

    current = frozenset(path for path, _ in serialized)
    _commit_feed_paths(app, domain, previous=previous, current=current)


def _atom_entry_for_post(
    app: Sphinx,
    post: Post,
    *,
    tag_labels: Mapping[str, str],
    category_labels: Mapping[str, str],
    author_labels: Mapping[str, str],
    body_html: str | None,
) -> AtomEntry:
    from .html_metadata import absolute_doc_url

    page_url = absolute_doc_url(app, post.docname)
    urls = post_urls(page_url, post.canonical_url, post.external_url)
    return atom_entry(
        post,
        urls=urls,
        body_html=body_html,
        tag_labels=tag_labels,
        category_labels=category_labels,
        author_labels=author_labels,
    )


def _commit_feed_paths(
    app: Sphinx,
    domain: MaatlogDomain,
    *,
    previous: set[str],
    current: frozenset[str],
) -> None:
    """Delete stale feed files and persist the feeds owner only."""
    from .outputs import (
        GeneratedOutputManifest,
        commit_generated_outputs,
        get_owned_paths,
        load_persisted_outputs,
        persist_outputs,
        store_owned_paths,
    )

    outdir = Path(app.outdir)
    commit_generated_outputs(
        outdir,
        GeneratedOutputManifest(owner="feeds", paths=frozenset(previous)),
        GeneratedOutputManifest(owner="feeds", paths=current),
    )
    store_owned_paths(domain, "feeds", current)
    # Preserve pages from domain (set by commit_page_outputs) or sidecar.
    pages = get_owned_paths(domain, "pages")
    if not pages:
        pages = load_persisted_outputs(Path(app.doctreedir))["pages"]
    persist_outputs(Path(app.doctreedir), {"pages": pages, "feeds": current})


@dataclass(frozen=True, slots=True)
class _StagedFeed:
    relative_path: str
    target: Path
    temp: Path


def _stage_all_xml(outdir: Path, items: Sequence[tuple[str, bytes]]) -> list[_StagedFeed]:
    """Write feed bytes to temp files under each destination parent directory."""
    from .outputs import safe_owned_path

    staged: list[_StagedFeed] = []
    try:
        for relative, content in items:
            try:
                target = safe_owned_path(outdir, PurePosixPath(relative))
            except MaatlogBuildError as exc:
                if exc.diagnostics and exc.diagnostics[0].code == "maatlog.archive.output-unsafe":
                    raise MaatlogBuildError(
                        [
                            Diagnostic(
                                code="maatlog.feed.output-unsafe",
                                message=item.message,
                                field=item.field,
                                value=item.value,
                                expected=item.expected,
                            )
                            for item in exc.diagnostics
                        ]
                    ) from exc
                raise
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=".maatlog-feed-",
                suffix=".tmp",
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
            staged.append(_StagedFeed(relative_path=relative, target=target, temp=temp_path))
    except Exception:
        _cleanup_staged(staged)
        raise
    return staged


def _validate_all_xml(staged: Sequence[_StagedFeed]) -> None:
    """Parse each staged file; leave temps in place on success."""
    for item in staged:
        try:
            fromstring(item.temp.read_bytes())
        except Exception as exc:  # noqa: BLE001
            _cleanup_staged(staged)
            raise MaatlogBuildError(
                [
                    Diagnostic(
                        code="maatlog.feed.xml-invalid",
                        message=f"Generated Atom feed is not valid XML: {item.relative_path}",
                        field="path",
                        value=item.relative_path,
                        expected="well-formed Atom XML",
                    )
                ]
            ) from exc


def _replace_all(staged: Sequence[_StagedFeed]) -> None:
    """Atomically replace each destination with its staged temp file."""
    try:
        for item in staged:
            item.temp.replace(item.target)
    except Exception:
        # Best-effort cleanup of any remaining temps.
        _cleanup_staged(staged)
        raise


def _cleanup_staged(staged: Sequence[_StagedFeed]) -> None:
    for item in staged:
        item.temp.unlink(missing_ok=True)

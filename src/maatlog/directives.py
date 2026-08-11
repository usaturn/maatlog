"""``maatlog:post-list`` directive and HTML / non-HTML node projection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, cast

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.builders import Builder
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import make_refnode
from sphinx.writers.html5 import HTML5Translator
from sphinx.writers.latex import LaTeXTranslator
from sphinx.writers.text import TextTranslator

from .archives import PostFilter, filter_posts
from .config import TAXONOMY_KEY_PATTERN, MaatlogConfig
from .errors import Diagnostic, MaatlogBuildError
from .model import Post
from .views import image_url_for, post_card_view, relative_page_url_for

_MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
_POST_CARD_TEMPLATE = "maatlog/components/post-card.html"
# Plural option / field names → singular axis label for diagnostics.
_AXIS_SINGULAR: Mapping[str, str] = {
    "tags": "tag",
    "categories": "category",
    "authors": "author",
}


class post_list(nodes.General, nodes.Element):
    """Placeholder node expanded after the published snapshot is final."""


def comma_separated_ids(argument: str | None) -> tuple[str, ...]:
    """Parse a non-empty comma-separated taxonomy ID list (raises ``ValueError``)."""
    if argument is None:
        msg = "expected a non-empty comma-separated list of IDs"
        raise ValueError(msg)
    raw = str(argument).strip()
    if not raw:
        msg = "expected a non-empty comma-separated list of IDs"
        raise ValueError(msg)
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(not part for part in parts):
        msg = "expected a non-empty comma-separated list of IDs"
        raise ValueError(msg)
    invalid = [part for part in parts if TAXONOMY_KEY_PATTERN.fullmatch(part) is None]
    if invalid:
        msg = f"invalid taxonomy ID(s): {', '.join(invalid)}"
        raise ValueError(msg)
    return tuple(dict.fromkeys(parts))


def month_value(argument: str | None) -> str:
    """Parse a single ``YYYY-MM`` month value (raises ``ValueError``)."""
    if argument is None:
        msg = "expected a YYYY-MM month"
        raise ValueError(msg)
    value = str(argument).strip()
    if _MONTH_PATTERN.fullmatch(value) is None:
        msg = "expected a YYYY-MM month"
        raise ValueError(msg)
    return value


def positive_int(argument: str | None) -> int:
    """Parse a positive integer limit (raises ``ValueError``)."""
    try:
        value = int(str(argument).strip(), 10)
    except (TypeError, ValueError) as exc:
        msg = "expected a positive integer"
        raise ValueError(msg) from exc
    if value < 1:
        msg = "expected a positive integer"
        raise ValueError(msg)
    return value


_KNOWN_POST_LIST_OPTIONS = frozenset({"tags", "categories", "authors", "month", "limit"})


class _PostListOptionSpec(dict[str, Any]):
    """Accept any option name so unknown keys become MaatLog diagnostics."""

    def __contains__(self, key: object) -> bool:
        return True

    def __getitem__(self, key: str) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        # Store the raw value; :meth:`PostListDirective.run` rejects unknown names.
        return directives.unchanged


class PostListDirective(SphinxDirective):
    """Embed a filtered list of published posts (no pagination)."""

    has_content = False
    required_arguments = 0
    optional_arguments = 0
    # ``unchanged`` so we can emit MaatLog diagnostics with source/line ourselves.
    # Unknown option names are accepted here and rejected in :meth:`run`.
    option_spec = _PostListOptionSpec(
        {
            "tags": directives.unchanged,
            "categories": directives.unchanged,
            "authors": directives.unchanged,
            "month": directives.unchanged,
            "limit": directives.unchanged,
        }
    )

    def run(self) -> list[nodes.Node]:
        source, line = self.get_source_info()
        diagnostics: list[Diagnostic] = []

        for option_name, option_raw in self.options.items():
            if option_name in _KNOWN_POST_LIST_OPTIONS:
                continue
            diagnostics.append(
                Diagnostic(
                    code="maatlog.archive.option-invalid",
                    message="Unknown post-list option",
                    source=source,
                    line=line,
                    field=str(option_name),
                    value=repr(option_raw),
                    expected=f"one of {', '.join(sorted(_KNOWN_POST_LIST_OPTIONS))}",
                )
            )

        tags = _parse_id_option("tags", self.options.get("tags"), source, line, diagnostics)
        categories = _parse_id_option("categories", self.options.get("categories"), source, line, diagnostics)
        authors = _parse_id_option("authors", self.options.get("authors"), source, line, diagnostics)
        month = _parse_month_option(self.options.get("month"), source, line, diagnostics)
        limit = _parse_limit_option(self.options.get("limit"), source, line, diagnostics)

        config = MaatlogConfig.from_sphinx(self.config)
        diagnostics.extend(
            _validate_allowlists(
                tags=tags,
                categories=categories,
                authors=authors,
                config=config,
                source=source,
                line=line,
            )
        )
        if diagnostics:
            raise MaatlogBuildError(diagnostics)

        node = post_list(
            "",
            maatlog_filter=PostFilter(
                tags=tags or (),
                categories=categories or (),
                authors=authors or (),
                month=month,
            ),
            maatlog_limit=limit,
            docname=self.env.docname,
        )
        self.set_source_info(node)
        return [node]


def process_post_list_nodes(app: Sphinx, doctree: nodes.document, docname: str) -> None:
    """Resolve ``post_list`` nodes after the published snapshot is available.

    HTML builders keep the node for the HTML visitor (post-card render). Other
    builders replace it with a standard bullet list of titles and references.

    Runs on ``doctree-resolved`` (after Sphinx xref resolution), so internal
    posts must become concrete ``nodes.reference`` via ``make_refnode`` rather
    than late ``pending_xref`` nodes that would never resolve.
    """
    domain = app.env.get_domain("maatlog")
    published = cast(tuple[Post, ...], domain.published_posts())  # type: ignore[attr-defined]
    config = MaatlogConfig.from_sphinx(app.config)
    is_html = app.builder.format == "html"

    for node in list(doctree.findall(post_list)):
        post_filter = cast(PostFilter, node["maatlog_filter"])
        limit = cast(int | None, node.get("maatlog_limit"))
        matched = filter_posts(published, post_filter, timezone=config.timezone)
        if limit is not None:
            matched = matched[:limit]
        if is_html:
            node["maatlog_posts"] = matched
            continue
        node.replace_self(_bullet_list_for_posts(matched, builder=app.builder, from_docname=docname))


def html_visit_post_list(self: HTML5Translator, node: post_list) -> None:
    posts = cast(tuple[Post, ...], node.get("maatlog_posts", ()))
    docname = str(node["docname"]) if "docname" in node else self.builder.current_docname
    builder = self.builder
    cards_html: list[str] = []
    for post in posts:
        card = post_card_view(
            post,
            page_url=relative_page_url_for(builder, docname, post.docname),
            image_url=image_url_for(builder, docname, post.image_uri),
            slug=post.slug,
        )
        cards_html.append(_render_post_card(builder, asdict(card)))
    body = "".join(cards_html)
    self.body.append(f'<div class="maatlog-post-list" data-maatlog-component="post-list">{body}</div>')
    raise nodes.SkipNode


def html_depart_post_list(self: HTML5Translator, node: post_list) -> None:
    del self, node


def text_visit_post_list(self: TextTranslator, node: post_list) -> None:
    del self
    raise nodes.SkipNode


def latex_visit_post_list(self: LaTeXTranslator, node: post_list) -> None:
    del self
    raise nodes.SkipNode


def _render_post_card(builder: Any, card: Mapping[str, Any]) -> str:
    templates = getattr(builder, "templates", None)
    if templates is not None and hasattr(templates, "render"):
        try:
            return cast(str, templates.render(_POST_CARD_TEMPLATE, {"card": card}))
        except Exception:  # noqa: BLE001 — fall back to minimal markup
            pass
    return _fallback_post_card_html(card)


def _fallback_post_card_html(card: Mapping[str, Any]) -> str:
    slug = card.get("slug")
    slug_attr = f' data-slug="{_escape_html(str(slug))}"' if slug else ""
    title = _escape_html(str(card.get("title") or ""))
    external = card.get("external_url")
    page_url = card.get("page_url") or ""
    if external:
        link = (
            f'<a class="maatlog-external-link" href="{_escape_html(str(external))}" '
            f'rel="noopener noreferrer">{title}</a>'
        )
    else:
        link = f'<a href="{_escape_html(str(page_url))}">{title}</a>'
    return (
        f'<article class="maatlog-post-card" data-maatlog-component="post-card"{slug_attr}>'
        f'<h2 class="maatlog-post-card-title">{link}</h2>'
        f"</article>"
    )


def _escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _bullet_list_for_posts(
    posts: Sequence[Post],
    *,
    builder: Builder,
    from_docname: str,
) -> nodes.Node:
    if not posts:
        return nodes.bullet_list()

    bullet = nodes.bullet_list()
    for post in posts:
        item = nodes.list_item()
        para = nodes.paragraph()
        if post.external_url:
            ref = nodes.reference("", post.title, refuri=post.external_url)
            para += ref
        else:
            # Concrete internal link — pending_xref is already past resolution.
            contnode = nodes.inline("", post.title)
            ref = make_refnode(
                builder,
                from_docname,
                post.docname,
                None,
                contnode,
                post.title,
            )
            para += ref
        if post.published_at is not None:
            para += nodes.Text(f" ({post.published_at.isoformat()})")
        item += para
        bullet += item
    return bullet


def _parse_id_option(
    field: str,
    raw: object | None,
    source: str | None,
    line: int | None,
    diagnostics: list[Diagnostic],
) -> tuple[str, ...] | None:
    if raw is None:
        return None
    try:
        return comma_separated_ids(str(raw))
    except ValueError as exc:
        diagnostics.append(
            Diagnostic(
                code="maatlog.archive.option-invalid",
                message="Invalid post-list option",
                source=source,
                line=line,
                field=field,
                value=repr(raw),
                expected=str(exc),
            )
        )
        return None


def _parse_month_option(
    raw: object | None,
    source: str | None,
    line: int | None,
    diagnostics: list[Diagnostic],
) -> str | None:
    if raw is None:
        return None
    try:
        return month_value(str(raw))
    except ValueError as exc:
        diagnostics.append(
            Diagnostic(
                code="maatlog.archive.option-invalid",
                message="Invalid post-list option",
                source=source,
                line=line,
                field="month",
                value=repr(raw),
                expected=str(exc),
            )
        )
        return None


def _parse_limit_option(
    raw: object | None,
    source: str | None,
    line: int | None,
    diagnostics: list[Diagnostic],
) -> int | None:
    if raw is None:
        return None
    try:
        return positive_int(str(raw))
    except ValueError as exc:
        diagnostics.append(
            Diagnostic(
                code="maatlog.archive.option-invalid",
                message="Invalid post-list option",
                source=source,
                line=line,
                field="limit",
                value=repr(raw),
                expected=str(exc),
            )
        )
        return None


def _validate_allowlists(
    *,
    tags: tuple[str, ...] | None,
    categories: tuple[str, ...] | None,
    authors: tuple[str, ...] | None,
    config: MaatlogConfig,
    source: str | None,
    line: int | None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    checks: tuple[tuple[str, tuple[str, ...] | None, Mapping[str, str] | None], ...] = (
        ("tags", tags, config.tags),
        ("categories", categories, config.categories),
        ("authors", authors, config.authors),
    )
    for field, values, allowlist in checks:
        if not values or allowlist is None:
            continue
        axis_name = _AXIS_SINGULAR[field]
        for taxonomy_id in values:
            if taxonomy_id not in allowlist:
                diagnostics.append(
                    Diagnostic(
                        code="maatlog.archive.filter-undefined",
                        message=f"Undefined {axis_name} ID in post-list",
                        source=source,
                        line=line,
                        field=field,
                        value=repr(taxonomy_id),
                        expected="an ID present in the corresponding MaatLog taxonomy config",
                    )
                )
    return diagnostics

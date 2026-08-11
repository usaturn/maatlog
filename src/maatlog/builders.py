"""Builder capability classification for MaatLog feature gates."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sphinx.application import Sphinx
from sphinx.builders import Builder
from sphinx.util import logging

logger = logging.getLogger(__name__)

PARTIAL_SUPPORT_CODE = "maatlog.builder.partial-support"
_PARTIAL_WARNED_ATTR = "_maatlog_partial_support_warned"


class BuilderCapability(StrEnum):
    """Supported feature surface for a Sphinx builder.

    ``FULL_HTML`` (``html`` / ``dirhtml``): archives, Theme API validation, Atom
    feeds, and HTML metadata are active.

    ``DOCUMENT_ONLY`` (non-HTML formats such as ``text`` / ``latex``): post body
    and post roles resolve; taxonomy roles render as inline labels; HTML-only
    features are skipped without hard failures.

    ``PARTIAL_HTML`` (other HTML builders such as ``singlehtml``): same document
    surface as ``DOCUMENT_ONLY``, with a one-time partial-support warning.
    Archives, Theme API validation, feeds, and HTML metadata stay disabled.
    """

    FULL_HTML = "full-html"
    DOCUMENT_ONLY = "document-only"
    PARTIAL_HTML = "partial-html"


def builder_capability(builder: Builder) -> BuilderCapability:
    """Classify *builder* into a MaatLog capability tier."""
    name = getattr(builder, "name", None)
    if name in {"html", "dirhtml"}:
        return BuilderCapability.FULL_HTML
    if getattr(builder, "format", None) != "html":
        return BuilderCapability.DOCUMENT_ONLY
    return BuilderCapability.PARTIAL_HTML


def is_full_html_builder(builder: Any) -> bool:
    """Return True when MaatLog's full HTML feature surface is enabled."""
    return builder_capability(builder) is BuilderCapability.FULL_HTML


def warn_partial_support_once(app: Sphinx) -> None:
    """Emit ``maatlog.builder.partial-support`` at most once per application.

    No-op for full HTML and document-only builders. Uses an application
    attribute flag so parallel or repeated handler calls stay silent.
    """
    if app.__dict__.get(_PARTIAL_WARNED_ATTR):
        return
    if builder_capability(app.builder) is not BuilderCapability.PARTIAL_HTML:
        return
    app.__dict__[_PARTIAL_WARNED_ATTR] = True
    # Sphinx appends ``[type.subtype]`` → ``[maatlog.builder.partial-support]``.
    logger.warning(
        "MaatLog provides limited support for builder %r: archives, Theme API "
        "validation, Atom feeds, and HTML metadata are disabled; use html or "
        "dirhtml for full support",
        app.builder.name,
        type="maatlog",
        subtype="builder.partial-support",
    )

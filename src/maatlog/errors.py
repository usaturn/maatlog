from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sphinx.errors import SphinxError

# Long diagnostic values (excerpts, bodies, huge paths) stay actionable without flooding logs.
_MAX_DIAGNOSTIC_VALUE_LENGTH = 120
# Strip userinfo from http(s) URLs embedded in diagnostic values (including repr-quoted forms).
_HTTP_USERINFO_RE = re.compile(r"(https?://)([^/@\s\"']+)@", re.IGNORECASE)


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    source: str | None = None
    line: int | None = None
    field: str | None = None
    value: str | None = None
    expected: str | None = None


def diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[str, int, str]:
    return (diagnostic.source or "", diagnostic.line if diagnostic.line is not None else -1, diagnostic.code)


def format_location(source: str | None, line: int | None) -> str | None:
    """Return ``source`` or ``source:line`` for human-readable diagnostic prefixes."""
    if source is None:
        return None
    if line is not None:
        return f"{source}:{line}"
    return source


def redact_userinfo_in_text(text: str) -> str:
    """Remove URL userinfo from *text* for safe diagnostic display."""
    return _HTTP_USERINFO_RE.sub(r"\1", text)


def safe_value(diagnostic: Diagnostic) -> str | None:
    """Return a redacted, length-capped representation of ``diagnostic.value``."""
    if diagnostic.value is None:
        return None
    value = redact_userinfo_in_text(diagnostic.value)
    if len(value) > _MAX_DIAGNOSTIC_VALUE_LENGTH:
        return f"{value[: _MAX_DIAGNOSTIC_VALUE_LENGTH - 3]}..."
    return value


def format_diagnostic(diagnostic: Diagnostic) -> str:
    """Format a diagnostic in the stable MaatLog contract form.

    ``<source>:<line>: ERROR: [code] <summary>; field=...; value=...; expected=...``
    Location is omitted when unknown. Optional field/value/expected appear only when set.
    """
    head = f"ERROR: [{diagnostic.code}] {diagnostic.message}"
    location = format_location(diagnostic.source, diagnostic.line)
    if location is not None:
        head = f"{location}: {head}"
    parts = [head]
    for name, value in (
        ("field", diagnostic.field),
        ("value", safe_value(diagnostic)),
        ("expected", diagnostic.expected),
    ):
        if value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


class MaatlogBuildError(SphinxError):
    category = "MaatLog build error"

    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        self.diagnostics = tuple(sorted(diagnostics, key=diagnostic_sort_key))
        super().__init__("\n".join(format_diagnostic(item) for item in self.diagnostics))

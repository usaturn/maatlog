"""Author profile data model: external links and their built-in icons.

``maatlog_author_profiles`` is the configuration entry point for rich author
data. Display names stay in ``maatlog_authors``; this module never carries one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict

from .errors import Diagnostic
from .urls import is_external_link_url

LINK_INVALID_CODE: Final = "maatlog.author.link-invalid"
CONFIG_INVALID_CODE: Final = "maatlog.config.invalid"

#: Icon used for every link type MaatLog ships no brand icon for.
GENERIC_LINK_ICON: Final = "link"

#: Link type to its default label and built-in icon name.
#:
#: ``linkedin`` maps to the generic icon on purpose: Simple Icons removed the
#: LinkedIn logo, so MaatLog ships no LinkedIn brand mark. See ``NOTICE``.
KNOWN_LINK_TYPES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "github": ("GitHub", "github"),
        "x": ("X", "x"),
        "bluesky": ("Bluesky", "bluesky"),
        "linkedin": ("LinkedIn", GENERIC_LINK_ICON),
        "website": ("Website", "website"),
        "rss": ("RSS", "rss"),
    }
)

_PROFILE_KEYS: Final = frozenset({"links"})
_LINK_KEYS: Final = frozenset({"type", "url", "label"})


class AuthorLink(BaseModel):
    """One external link of an author. ``label`` and ``icon`` are always resolved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    url: str
    label: str
    icon: str


class AuthorProfile(BaseModel):
    """Rich author data. Only ``links`` exists today; more fields land with #70."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    links: tuple[AuthorLink, ...] = ()


def validate_author_profile(field: str, value: Any, diagnostics: list[Diagnostic]) -> AuthorProfile | None:
    """Validate one profile mapping, appending diagnostics for every problem found.

    *field* is the dotted path of this profile (``maatlog_author_profiles.<slug>``)
    and prefixes the ``field`` of every diagnostic raised here.
    """
    if not isinstance(value, Mapping):
        _config_invalid(diagnostics, field, value, "a mapping with a links key")
        return None

    mapping = cast(Mapping[object, object], value)
    unknown = sorted(str(key) for key in mapping if key not in _PROFILE_KEYS)
    if unknown:
        _config_invalid(diagnostics, field, unknown, "only the links key")
        return None

    raw_links = mapping.get("links")
    if raw_links is None:
        return AuthorProfile(links=())
    if isinstance(raw_links, (str, bytes)) or not isinstance(raw_links, Sequence):
        _config_invalid(diagnostics, f"{field}.links", raw_links, "a sequence of link mappings")
        return None

    links: list[AuthorLink] = []
    is_valid = True
    for index, item in enumerate(cast(Sequence[object], raw_links)):
        link = _validate_link(f"{field}.links[{index}]", item, diagnostics)
        if link is None:
            is_valid = False
            continue
        links.append(link)
    if not is_valid:
        return None
    return AuthorProfile(links=tuple(links))


def _validate_link(field: str, value: object, diagnostics: list[Diagnostic]) -> AuthorLink | None:
    if not isinstance(value, Mapping):
        _link_invalid(diagnostics, field, value, "a mapping with type and url")
        return None

    mapping = cast(Mapping[object, object], value)
    unknown = sorted(str(key) for key in mapping if key not in _LINK_KEYS)
    if unknown:
        _link_invalid(diagnostics, field, unknown, "only type, url, and label")
        return None

    is_valid = True

    raw_type = mapping.get("type")
    link_type = raw_type.strip().lower() if isinstance(raw_type, str) else ""
    if not link_type:
        _link_invalid(diagnostics, f"{field}.type", raw_type, "a non-empty link type")
        is_valid = False

    raw_url = mapping.get("url")
    url = raw_url.strip() if isinstance(raw_url, str) else ""
    if not url or not is_external_link_url(url):
        _link_invalid(diagnostics, f"{field}.url", raw_url, "an absolute http or https URL")
        is_valid = False

    raw_label = mapping.get("label")
    label: str | None = None
    if raw_label is not None:
        if not isinstance(raw_label, str) or not raw_label.strip():
            _link_invalid(diagnostics, f"{field}.label", raw_label, "a non-empty label")
            is_valid = False
        else:
            label = raw_label.strip()

    if not is_valid:
        return None

    default_label, icon = KNOWN_LINK_TYPES.get(link_type, (link_type, GENERIC_LINK_ICON))
    return AuthorLink(type=link_type, url=url, label=label or default_label, icon=icon)


def _config_invalid(diagnostics: list[Diagnostic], field: str, value: object, expected: str) -> None:
    diagnostics.append(
        Diagnostic(
            code=CONFIG_INVALID_CODE,
            message=f"Invalid {field}",
            field=field,
            value=repr(value),
            expected=expected,
        )
    )


def _link_invalid(diagnostics: list[Diagnostic], field: str, value: object, expected: str) -> None:
    diagnostics.append(
        Diagnostic(
            code=LINK_INVALID_CODE,
            message=f"Invalid {field}",
            field=field,
            value=repr(value),
            expected=expected,
        )
    )

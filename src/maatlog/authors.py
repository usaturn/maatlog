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
from .urls import is_absolute_http_url, is_relative_docname

LINK_INVALID_CODE: Final = "maatlog.author.link-invalid"
CONFIG_INVALID_CODE: Final = "maatlog.config.invalid"

#: Expected value reported when ``featured_posts`` repeats the same slug.
_EXPECTED_NO_DUPLICATES: Final = "a sequence without duplicate slugs"

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

_PROFILE_KEYS: Final = frozenset(
    {"role", "avatar", "bio_short", "interests", "links", "featured_posts", "about_docname"}
)
_LINK_KEYS: Final = frozenset({"type", "url", "label"})

#: Tells "the key was present but malformed" apart from "the key was absent".
_INVALID: Final = object()

_EXPECTED_MAPPING: Final = "a mapping of " + ", ".join(sorted(_PROFILE_KEYS))
_EXPECTED_TEXT_SEQUENCE: Final = "a sequence of non-empty strings"


class AuthorLink(BaseModel):
    """One external link of an author. ``label`` and ``icon`` are always resolved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    url: str
    label: str
    icon: str


class AuthorProfile(BaseModel):
    """Rich author data configured through ``maatlog_author_profiles``.

    Every field is optional so a profile that only sets ``links`` keeps working.
    Cross-references (``featured_posts`` slugs, ``about_docname``, the avatar
    file) are resolved later against the domain index and the source tree; this
    model only checks the shape of the configured value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str | None = None
    avatar: str | None = None
    bio_short: str | None = None
    interests: tuple[str, ...] = ()
    links: tuple[AuthorLink, ...] = ()
    featured_posts: tuple[str, ...] = ()
    about_docname: str | None = None


def validate_author_profile(field: str, value: Any, diagnostics: list[Diagnostic]) -> AuthorProfile | None:
    """Validate one profile mapping, appending diagnostics for every problem found.

    *field* is the dotted path of this profile (``maatlog_author_profiles.<slug>``)
    and prefixes the ``field`` of every diagnostic raised here.

    Only the shape of the configured value is checked. Whether a featured slug
    exists, an About document is present, or an avatar file is readable needs the
    build environment and is decided in :mod:`maatlog.profiles`.
    """
    if not isinstance(value, Mapping):
        _config_invalid(diagnostics, field, value, _EXPECTED_MAPPING)
        return None

    mapping = cast(Mapping[object, object], value)
    unknown = sorted(str(key) for key in mapping if key not in _PROFILE_KEYS)
    if unknown:
        _config_invalid(diagnostics, field, unknown, _EXPECTED_MAPPING)
        return None

    role = _optional_text(mapping, "role", field, diagnostics)
    avatar = _optional_text(mapping, "avatar", field, diagnostics)
    bio_short = _optional_text(mapping, "bio_short", field, diagnostics)
    interests = _text_sequence(mapping, "interests", field, diagnostics)
    featured_posts = _text_sequence(mapping, "featured_posts", field, diagnostics)
    about_docname = _optional_docname(mapping, "about_docname", field, diagnostics)
    links = _link_sequence(mapping, field, diagnostics)

    # Every validator has already appended its diagnostics, so all problems in
    # this profile are reported even though the first failure ends the function.
    if any(item is _INVALID for item in (role, avatar, bio_short, about_docname)):
        return None
    if interests is None or featured_posts is None or links is None:
        return None
    if len(set(featured_posts)) != len(featured_posts):
        _config_invalid(diagnostics, f"{field}.featured_posts", featured_posts, _EXPECTED_NO_DUPLICATES)
        return None

    return AuthorProfile(
        role=cast(str | None, role),
        avatar=cast(str | None, avatar),
        bio_short=cast(str | None, bio_short),
        interests=interests,
        links=links,
        featured_posts=featured_posts,
        about_docname=cast(str | None, about_docname),
    )


def _link_sequence(
    mapping: Mapping[object, object], field: str, diagnostics: list[Diagnostic]
) -> tuple[AuthorLink, ...] | None:
    raw_links = mapping.get("links")
    if raw_links is None:
        return ()
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
    return tuple(links)


def _optional_text(
    mapping: Mapping[object, object], key: str, field: str, diagnostics: list[Diagnostic]
) -> str | None | object:
    """Return the stripped text, ``None`` when absent, or ``_INVALID`` when malformed."""
    raw = mapping.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        _config_invalid(diagnostics, f"{field}.{key}", raw, "a non-empty string")
        return _INVALID
    return raw.strip()


def _text_sequence(
    mapping: Mapping[object, object], key: str, field: str, diagnostics: list[Diagnostic]
) -> tuple[str, ...] | None:
    """Return the stripped values, ``()`` when absent, or ``None`` when malformed."""
    raw = mapping.get(key)
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        _config_invalid(diagnostics, f"{field}.{key}", raw, _EXPECTED_TEXT_SEQUENCE)
        return None
    values: list[str] = []
    for item in cast(Sequence[object], raw):
        if not isinstance(item, str) or not item.strip():
            _config_invalid(diagnostics, f"{field}.{key}", item, _EXPECTED_TEXT_SEQUENCE)
            return None
        values.append(item.strip())
    return tuple(values)


def _optional_docname(
    mapping: Mapping[object, object], key: str, field: str, diagnostics: list[Diagnostic]
) -> str | None | object:
    raw = mapping.get(key)
    if raw is None:
        return None
    # Untrimmed values otherwise pass is_relative_docname() and only surface
    # later as a confusing ``maatlog.author.about-unknown`` build error.
    value = raw.strip() if isinstance(raw, str) else raw
    if not is_relative_docname(value):
        _config_invalid(diagnostics, f"{field}.{key}", raw, "a relative Sphinx document name")
        return _INVALID
    return value


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
    if not url or not is_absolute_http_url(url):
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

from collections.abc import Mapping, Sequence
from enum import StrEnum
from re import compile as re_compile
from types import MappingProxyType
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator
from sphinx.config import Config

from .errors import Diagnostic, MaatlogBuildError


class TaxonomyAxis(StrEnum):
    TAG = "tag"
    CATEGORY = "category"
    AUTHOR = "author"
    MONTH = "month"


CONFIG_VALUES = {
    "maatlog_timezone": ("UTC", "env"),
    "maatlog_tags": (None, "env"),
    "maatlog_categories": (None, "env"),
    "maatlog_authors": (None, "env"),
    "maatlog_archive_docname": ("blog", "env"),
    "maatlog_page_size": (10, "env"),
    "maatlog_generate_feeds": (True, "html"),
    "maatlog_feed_taxonomies": (("tag", "category", "author", "month"), "html"),
    "maatlog_feed_limit": (20, "html"),
}

TAXONOMY_KEY_PATTERN = re_compile(r"[a-z0-9][a-z0-9._-]*\Z")


class MaatlogConfig(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    timezone: ZoneInfo
    tags: Mapping[str, str] | None
    categories: Mapping[str, str] | None
    authors: Mapping[str, str] | None
    archive_docname: str
    page_size: int
    generate_feeds: bool
    feed_taxonomies: tuple[TaxonomyAxis, ...]
    feed_limit: int

    @field_validator("tags", "categories", "authors")
    @classmethod
    def _freeze_taxonomy_mapping(cls, value: Mapping[str, str] | None) -> Mapping[str, str] | None:
        if value is None:
            return None
        return MappingProxyType(dict(value))

    @classmethod
    def from_sphinx(cls, config: Config) -> "MaatlogConfig":
        return cls.from_values({name: getattr(config, name) for name in CONFIG_VALUES})

    @classmethod
    def from_values(cls, values: Mapping[str, Any]) -> "MaatlogConfig":
        resolved = {name: values.get(name, default) for name, (default, _) in CONFIG_VALUES.items()}
        diagnostics: list[Diagnostic] = []

        timezone = _validate_timezone(resolved["maatlog_timezone"], diagnostics)
        tags = _validate_taxonomy_mapping("maatlog_tags", resolved["maatlog_tags"], diagnostics)
        categories = _validate_taxonomy_mapping("maatlog_categories", resolved["maatlog_categories"], diagnostics)
        authors = _validate_taxonomy_mapping("maatlog_authors", resolved["maatlog_authors"], diagnostics)
        archive_docname = _validate_docname(resolved["maatlog_archive_docname"], diagnostics)
        page_size = _validate_positive_int("maatlog_page_size", resolved["maatlog_page_size"], diagnostics)
        generate_feeds = _validate_bool("maatlog_generate_feeds", resolved["maatlog_generate_feeds"], diagnostics)
        feed_taxonomies = _validate_feed_taxonomies(resolved["maatlog_feed_taxonomies"], diagnostics)
        feed_limit = _validate_positive_int("maatlog_feed_limit", resolved["maatlog_feed_limit"], diagnostics)

        if diagnostics:
            raise MaatlogBuildError(diagnostics)

        assert timezone is not None
        assert archive_docname is not None
        assert page_size is not None
        assert generate_feeds is not None
        assert feed_taxonomies is not None
        assert feed_limit is not None
        return cls(
            timezone=timezone,
            tags=tags,
            categories=categories,
            authors=authors,
            archive_docname=archive_docname,
            page_size=page_size,
            generate_feeds=generate_feeds,
            feed_taxonomies=feed_taxonomies,
            feed_limit=feed_limit,
        )


def _invalid(diagnostics: list[Diagnostic], field: str, value: Any, expected: str) -> None:
    diagnostics.append(
        Diagnostic(
            code="maatlog.config.invalid",
            message=f"Invalid {field}",
            field=field,
            value=repr(value),
            expected=expected,
        )
    )


def _validate_timezone(value: Any, diagnostics: list[Diagnostic]) -> ZoneInfo | None:
    if not isinstance(value, str):
        _invalid(diagnostics, "maatlog_timezone", value, "an IANA timezone name")
        return None
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError:
        _invalid(diagnostics, "maatlog_timezone", value, "an IANA timezone name")
        return None


def _validate_taxonomy_mapping(field: str, value: Any, diagnostics: list[Diagnostic]) -> Mapping[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        _invalid(diagnostics, field, value, "a mapping of strings to strings")
        return None
    is_valid = True
    validated: dict[str, str] = {}
    mapping = cast(Mapping[object, object], value)
    for key, item in mapping.items():
        key_is_valid = isinstance(key, str) and TAXONOMY_KEY_PATTERN.fullmatch(key) is not None
        item_is_valid = isinstance(item, str) and bool(item.strip())
        if not key_is_valid:
            _invalid(diagnostics, field, key, "a lowercase taxonomy key")
            is_valid = False
        if not item_is_valid:
            _invalid(diagnostics, field, item, "a non-empty display name")
            is_valid = False
        if key_is_valid and item_is_valid:
            validated[cast(str, key)] = cast(str, item)
    if not is_valid:
        return None
    return MappingProxyType(validated)


def _validate_docname(value: Any, diagnostics: list[Diagnostic]) -> str | None:
    if not isinstance(value, str) or not value:
        _invalid(diagnostics, "maatlog_archive_docname", value, "a relative Sphinx document name")
        return None
    segments = value.split("/")
    if value.startswith("/") or value.endswith("/") or any(segment in {"", ".", ".."} for segment in segments):
        _invalid(diagnostics, "maatlog_archive_docname", value, "a relative Sphinx document name")
        return None
    return value


def _validate_positive_int(field: str, value: Any, diagnostics: list[Diagnostic]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _invalid(diagnostics, field, value, "a positive integer")
        return None
    return value


def _validate_bool(field: str, value: Any, diagnostics: list[Diagnostic]) -> bool | None:
    if not isinstance(value, bool):
        _invalid(diagnostics, field, value, "a boolean")
        return None
    return value


def _validate_feed_taxonomies(value: Any, diagnostics: list[Diagnostic]) -> tuple[TaxonomyAxis, ...] | None:
    if not isinstance(value, (list, tuple)):
        _invalid(diagnostics, "maatlog_feed_taxonomies", value, "a sequence of taxonomy axes")
        return None
    axes: list[TaxonomyAxis] = []
    for axis in cast(Sequence[object], value):
        if not isinstance(axis, str):
            _invalid(diagnostics, "maatlog_feed_taxonomies", value, "tag, category, author, or month")
            return None
        try:
            axes.append(TaxonomyAxis(axis))
        except ValueError:
            _invalid(diagnostics, "maatlog_feed_taxonomies", value, "tag, category, author, or month")
            return None
    return tuple(dict.fromkeys(axes))


def validate_config(app: Any, config: Config) -> None:
    del app
    MaatlogConfig.from_sphinx(config)


def register_config(app: Any) -> None:
    for name, (default, rebuild) in CONFIG_VALUES.items():
        app.add_config_value(name, default, rebuild)
    app.connect("config-inited", validate_config)

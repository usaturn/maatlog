"""MaatLog Theme API versioning and selected-theme validation."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Never, cast

from jinja2 import Environment, TemplateNotFound
from jinja2 import nodes as jinja_nodes
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sphinx.application import Sphinx

from .errors import Diagnostic, MaatlogBuildError

MANIFEST_FILENAME: Final = "maatlog-theme.toml"
MAATLOG_BASE_THEME: Final = "maatlog-base"
STYLESHEET_RELATIVE: Final = "static/maatlog.css"

REQUIRED_TEMPLATES: Final[tuple[str, ...]] = (
    "maatlog/post.html",
    "maatlog/archive.html",
    "maatlog/components/post-card.html",
    "maatlog/components/pagination.html",
    "maatlog/components/sidebar.html",
    "maatlog/components/feed-links.html",
)

REQUIRED_BLOCKS: Final[tuple[str, ...]] = (
    "maatlog_head",
    "maatlog_post_header",
    "maatlog_post_meta",
    "maatlog_post_body",
    "maatlog_post_navigation",
    "maatlog_archive_header",
    "maatlog_archive_items",
    "maatlog_pagination",
    "maatlog_sidebar",
)

# Page templates that must define (or inherit) all required blocks.
BLOCK_PAGE_TEMPLATES: Final[tuple[str, ...]] = (
    "maatlog/post.html",
    "maatlog/archive.html",
)


class ThemeImplementation(StrEnum):
    INHERITS_BASE = "inherits-base"
    STANDALONE = "standalone"


class ThemeApiVersion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    major: int
    minor: int

    @field_validator("major", "minor")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            msg = "version components must be non-negative"
            raise ValueError(msg)
        return value

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


class ThemeManifest(BaseModel):
    """Parsed `[maatlog]` table from `maatlog-theme.toml`.

    Unknown keys are ignored so minor extensions stay forward-compatible.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    api: ThemeApiVersion
    implementation: ThemeImplementation


CORE_THEME_API: Final = ThemeApiVersion(major=1, minor=0)


def is_compatible(core: ThemeApiVersion, theme: ThemeApiVersion) -> bool:
    """Return True when *theme* is compatible with *core* API.

    Same major is required; theme minor must not exceed core minor.
    """
    return core.major == theme.major and theme.minor <= core.minor


def is_html_theme_builder(builder: object) -> bool:
    """Return True when Theme API validation applies (full HTML only)."""
    from .builders import is_full_html_builder

    return is_full_html_builder(builder)


def parse_api_version(
    value: object,
    *,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
    core_api: ThemeApiVersion | None = None,
) -> ThemeApiVersion:
    """Parse a dotted ``major.minor`` Theme API version string."""
    if not isinstance(value, str):
        _invalid_manifest(
            field="api",
            value=value,
            expected='a version string like "1.0"',
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    parts = value.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        _invalid_manifest(
            field="api",
            value=value,
            expected='a version string like "1.0"',
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    major_s, minor_s = parts
    # Reject padded forms like "01.0" while still accepting "1.0".
    if major_s != str(int(major_s)) or minor_s != str(int(minor_s)):
        _invalid_manifest(
            field="api",
            value=value,
            expected='a version string like "1.0"',
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    return ThemeApiVersion(major=int(major_s), minor=int(minor_s))


def parse_and_validate_manifest(
    manifest: object,
    *,
    core_api: ThemeApiVersion,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
) -> ThemeManifest:
    """Parse a `[maatlog]` mapping and enforce core API compatibility.

    Diagnostics for both ``manifest-invalid`` and ``api-incompatible`` carry
    selected theme (``source``), resolved inheritance chain, core API, and
    theme API (where known) in message and/or value/expected fields.

    Raises:
        MaatlogBuildError: with ``maatlog.theme.manifest-invalid`` or
            ``maatlog.theme.api-incompatible``.
    """
    if not isinstance(manifest, Mapping):
        _invalid_manifest(
            field="maatlog",
            value=manifest,
            expected="a TOML table",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    fields = cast(Mapping[str, Any], manifest)

    if "api" not in fields:
        _invalid_manifest(
            field="api",
            value=None,
            expected='a version string like "1.0"',
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    if "implementation" not in fields:
        _invalid_manifest(
            field="implementation",
            value=None,
            expected='"inherits-base" or "standalone"',
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )

    api = parse_api_version(
        fields["api"],
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
        core_api=core_api,
    )
    implementation_raw = fields["implementation"]
    if implementation_raw not in {item.value for item in ThemeImplementation}:
        _invalid_manifest(
            field="implementation",
            value=implementation_raw,
            expected='"inherits-base" or "standalone"',
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )

    try:
        parsed = ThemeManifest.model_validate(
            {
                "api": api,
                "implementation": implementation_raw,
                **{key: value for key, value in fields.items() if key not in {"api", "implementation"}},
            }
        )
    except ValidationError:
        _invalid_manifest(
            field="maatlog",
            value=dict(fields),
            expected="api and implementation fields",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )

    if not is_compatible(core_api, parsed.api):
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.theme.api-incompatible",
                    message=(
                        "Theme API is incompatible with MaatLog core"
                        + _theme_context_suffix(
                            inheritance_chain=inheritance_chain,
                            core_api=core_api,
                            theme_api=parsed.api,
                        )
                    ),
                    source=theme_name,
                    field="api",
                    value=str(parsed.api),
                    expected=f"major={core_api.major} and minor<={core_api.minor}",
                )
            ]
        )
    return parsed


def load_maatlog_section(
    toml_text: str,
    *,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
    core_api: ThemeApiVersion | None = None,
) -> dict[str, Any]:
    """Load the required `[maatlog]` table from a theme manifest document."""
    try:
        document = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as error:
        _invalid_manifest(
            field="maatlog-theme.toml",
            value=str(error),
            expected="valid TOML",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    section = document.get("maatlog")
    if not isinstance(section, dict):
        _invalid_manifest(
            field="maatlog",
            value=section,
            expected="a [maatlog] table",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            core_api=core_api,
        )
    return cast(dict[str, Any], section)


def collect_template_block_names(environment: Environment, template_name: str) -> set[str]:
    """Collect Jinja block names from *template_name* and its extends parents."""
    seen: set[str] = set()
    blocks: set[str] = set()
    pending = [template_name]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            source, filename, _uptodate = environment.loader.get_source(environment, name)  # type: ignore[union-attr]
        except TemplateNotFound:
            continue
        ast = environment.parse(source, name, filename)
        for node in ast.find_all(jinja_nodes.Block):
            blocks.add(node.name)
        for node in ast.find_all(jinja_nodes.Extends):
            parent = node.template
            if isinstance(parent, jinja_nodes.Const) and isinstance(parent.value, str):
                pending.append(parent.value)
    return blocks


def validate_selected_theme(app: Sphinx) -> None:
    """Validate the selected HTML theme's MaatLog Theme API manifest.

    Non-HTML builders are skipped.

    The *final* selected theme root must ship ``maatlog-theme.toml``; missing
    manifests raise ``maatlog.theme.manifest-missing``. Parent-only manifests
    are insufficient.

    When a manifest is present, it is always parsed and version-checked.
    For ``standalone`` and ``inherits-base`` themes, required templates, Jinja
    blocks on post/archive pages, and ``static/maatlog.css`` are also checked.
    Diagnostics include selected theme, inheritance chain, and core/theme API.
    """
    builder = app.builder
    if not is_html_theme_builder(builder):
        return

    theme = getattr(builder, "theme", None)
    if theme is None:
        return

    theme_dirs = theme.get_theme_dirs()
    if not theme_dirs:
        return

    inheritance_chain = tuple(Path(path).name for path in theme_dirs)
    theme_name = theme.name
    manifest_path = Path(theme_dirs[0]) / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.theme.manifest-missing",
                    message=(
                        f"Selected theme is missing {MANIFEST_FILENAME!r}"
                        + _theme_context_suffix(
                            inheritance_chain=inheritance_chain,
                            core_api=CORE_THEME_API,
                        )
                    ),
                    source=theme_name,
                    field="manifest",
                    value=None,
                    expected=MANIFEST_FILENAME,
                )
            ]
        )

    section = load_maatlog_section(
        manifest_path.read_text(encoding="utf-8"),
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
        core_api=CORE_THEME_API,
    )
    manifest = parse_and_validate_manifest(
        section,
        core_api=CORE_THEME_API,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
    )

    if manifest.implementation is ThemeImplementation.INHERITS_BASE:
        if MAATLOG_BASE_THEME not in inheritance_chain:
            raise MaatlogBuildError(
                [
                    Diagnostic(
                        code="maatlog.theme.base-not-inherited",
                        message=(
                            f"Theme declares inherits-base but {MAATLOG_BASE_THEME!r} "
                            "is not in the inheritance chain"
                            + _theme_context_suffix(
                                inheritance_chain=inheritance_chain,
                                core_api=CORE_THEME_API,
                                theme_api=manifest.api,
                            )
                        ),
                        source=theme_name,
                        field="implementation",
                        value=manifest.implementation.value,
                        expected=f"inheritance chain containing {MAATLOG_BASE_THEME!r}",
                    )
                ]
            )

    _validate_required_templates(
        app,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
        theme_api=manifest.api,
    )
    _validate_required_blocks(
        app,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
        theme_api=manifest.api,
    )
    _validate_stylesheet(
        theme_dirs,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
        theme_api=manifest.api,
    )


def _jinja_environment(app: Sphinx) -> Environment | None:
    templates = getattr(app.builder, "templates", None)
    if templates is None:
        return None
    environment = getattr(templates, "environment", None)
    if not isinstance(environment, Environment):
        return None
    return environment


def _validate_required_templates(
    app: Sphinx,
    *,
    theme_name: str,
    inheritance_chain: Sequence[str],
    theme_api: ThemeApiVersion,
) -> None:
    environment = _jinja_environment(app)
    if environment is None:
        return
    for template_name in REQUIRED_TEMPLATES:
        try:
            environment.get_template(template_name)
        except TemplateNotFound:
            raise MaatlogBuildError(
                [
                    Diagnostic(
                        code="maatlog.theme.template-missing",
                        message=(
                            f"Required theme template {template_name!r} is missing"
                            + _theme_context_suffix(
                                inheritance_chain=inheritance_chain,
                                core_api=CORE_THEME_API,
                                theme_api=theme_api,
                            )
                        ),
                        source=theme_name,
                        field="template",
                        value=template_name,
                        expected="resolvable via Sphinx theme loader",
                    )
                ]
            ) from None


def _validate_required_blocks(
    app: Sphinx,
    *,
    theme_name: str,
    inheritance_chain: Sequence[str],
    theme_api: ThemeApiVersion,
) -> None:
    environment = _jinja_environment(app)
    if environment is None:
        return
    required = set(REQUIRED_BLOCKS)
    for template_name in BLOCK_PAGE_TEMPLATES:
        try:
            blocks = collect_template_block_names(environment, template_name)
        except TemplateNotFound:
            # template-missing already reported (or will be); skip block check.
            continue
        missing = sorted(required - blocks)
        if missing:
            raise MaatlogBuildError(
                [
                    Diagnostic(
                        code="maatlog.theme.block-missing",
                        message=(
                            f"Required Jinja blocks missing from {template_name!r}: "
                            f"{', '.join(missing)}"
                            + _theme_context_suffix(
                                inheritance_chain=inheritance_chain,
                                core_api=CORE_THEME_API,
                                theme_api=theme_api,
                            )
                        ),
                        source=theme_name,
                        field="block",
                        value=",".join(missing),
                        expected=",".join(REQUIRED_BLOCKS),
                    )
                ]
            )


def _validate_stylesheet(
    theme_dirs: Sequence[str | Path],
    *,
    theme_name: str,
    inheritance_chain: Sequence[str],
    theme_api: ThemeApiVersion,
) -> None:
    for directory in theme_dirs:
        candidate = Path(directory) / STYLESHEET_RELATIVE
        if candidate.is_file():
            return
    raise MaatlogBuildError(
        [
            Diagnostic(
                code="maatlog.theme.stylesheet-missing",
                message=(
                    f"Required stylesheet {STYLESHEET_RELATIVE!r} not found in inheritance chain"
                    + _theme_context_suffix(
                        inheritance_chain=inheritance_chain,
                        core_api=CORE_THEME_API,
                        theme_api=theme_api,
                    )
                ),
                source=theme_name,
                field="stylesheet",
                value=STYLESHEET_RELATIVE,
                expected="static/maatlog.css on the theme inheritance chain",
            )
        ]
    )


def _theme_context_suffix(
    *,
    inheritance_chain: Sequence[str] | None = None,
    core_api: ThemeApiVersion | None = None,
    theme_api: object | None = None,
) -> str:
    """Build a parenthetical context suffix shared by theme diagnostics."""
    parts: list[str] = []
    if inheritance_chain is not None:
        parts.append(f"chain={','.join(inheritance_chain)}")
    if core_api is not None:
        parts.append(f"core_api={core_api}")
    if theme_api is not None:
        parts.append(f"theme_api={theme_api}")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def _invalid_manifest(
    *,
    field: str,
    value: object,
    expected: str,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
    core_api: ThemeApiVersion | None = None,
) -> Never:
    raise MaatlogBuildError(
        [
            Diagnostic(
                code="maatlog.theme.manifest-invalid",
                message=(
                    "Invalid MaatLog theme manifest"
                    + _theme_context_suffix(
                        inheritance_chain=inheritance_chain,
                        core_api=core_api,
                    )
                ),
                source=theme_name,
                field=field,
                value=None if value is None else repr(value),
                expected=expected,
            )
        ]
    )

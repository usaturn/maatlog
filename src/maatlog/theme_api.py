"""MaatLog Theme API versioning and selected-theme validation."""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Never, cast

from jinja2 import Environment, TemplateNotFound
from jinja2 import nodes as jinja_nodes
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pygments.styles import get_style_by_name  # pyright: ignore[reportUnknownVariableType]
from pygments.util import ClassNotFound
from sphinx.application import Sphinx

from .config import PALETTE_NAME_PATTERN, MaatlogConfig
from .errors import Diagnostic, MaatlogBuildError

_get_style_by_name = cast(Callable[[str], object], get_style_by_name)

MANIFEST_FILENAME: Final = "maatlog-theme.toml"
MAATLOG_BASE_THEME: Final = "maatlog-base"
STYLESHEET_RELATIVE: Final = "static/maatlog.css"
PALETTES_RELATIVE: Final = "static/palettes"

REQUIRED_TEMPLATES: Final[tuple[str, ...]] = (
    "maatlog/post.html",
    "maatlog/archive.html",
    "maatlog/profile.html",
    "maatlog/components/post-card.html",
    "maatlog/components/pagination.html",
    "maatlog/components/sidebar.html",
    "maatlog/components/feed-links.html",
    "maatlog/components/author-links.html",
    "maatlog/components/right-rail.html",
    "maatlog/components/author-summary.html",
)

REQUIRED_BLOCKS: Final[tuple[str, ...]] = (
    "maatlog_head",
    "maatlog_post_header",
    "maatlog_post_meta",
    "maatlog_post_body",
    "maatlog_post_navigation",
    "maatlog_archive_header",
    "maatlog_archive_items",
    "maatlog_profile_header",
    "maatlog_profile_body",
    "maatlog_pagination",
    "maatlog_sidebar",
)

# Page templates that must define (or inherit) all required blocks.
BLOCK_PAGE_TEMPLATES: Final[tuple[str, ...]] = (
    "maatlog/post.html",
    "maatlog/archive.html",
    "maatlog/profile.html",
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


class PaletteDeclaration(BaseModel):
    """A theme's ``palettes`` / ``default_palette`` manifest declaration.

    Themes that declare no ``palettes`` are palette-unaware; they keep working
    exactly as they did before Theme API 1.5.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    palettes: tuple[str, ...]
    default_palette: str
    # Palette name to Pygments style name (Theme API 1.6, optional). Held as
    # pairs rather than a mapping so the frozen model stays hashable. Palettes
    # absent here fall back to ``theme.conf``.
    pygments: tuple[tuple[str, str], ...] = ()

    def pygments_style_for(self, palette: str) -> str | None:
        """Return the declared Pygments style for *palette*, if any."""
        for name, style in self.pygments:
            if name == palette:
                return style
        return None


CORE_THEME_API: Final = ThemeApiVersion(major=1, minor=22)


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


def parse_palette_declaration(
    section: Mapping[str, Any],
    *,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
) -> PaletteDeclaration | None:
    """Parse the optional palette declaration from a ``[maatlog]`` table.

    Returns ``None`` when the table declares no ``palettes``.

    Raises:
        MaatlogBuildError: with ``maatlog.theme.manifest-invalid``.
    """
    if "palettes" not in section:
        if "default_palette" in section:
            _invalid_manifest(
                field="palettes",
                value=section["default_palette"],
                expected="a list of palette names alongside default_palette",
                theme_name=theme_name,
                inheritance_chain=inheritance_chain,
            )
        if "pygments" in section:
            _invalid_manifest(
                field="pygments",
                value=section["pygments"],
                expected="a list of palette names alongside the pygments table",
                theme_name=theme_name,
                inheritance_chain=inheritance_chain,
            )
        return None

    raw_palettes: object = section["palettes"]
    if not isinstance(raw_palettes, (list, tuple)) or not raw_palettes:
        _invalid_manifest(
            field="palettes",
            value=cast(object, raw_palettes),
            expected="a non-empty list of palette names",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
        )
    names: list[str] = []
    for name in cast(Sequence[object], raw_palettes):
        if not isinstance(name, str) or PALETTE_NAME_PATTERN.fullmatch(name) is None or name in names:
            _invalid_manifest(
                field="palettes",
                value=name,
                expected="a unique lowercase palette name matching [a-z0-9][a-z0-9-]*",
                theme_name=theme_name,
                inheritance_chain=inheritance_chain,
            )
        names.append(name)

    default: object = section.get("default_palette")
    if not isinstance(default, str) or default not in names:
        _invalid_manifest(
            field="default_palette",
            value=default,
            expected=f"one of {', '.join(names)}",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
        )
    pygments = _parse_pygments_table(
        section,
        names,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
    )
    return PaletteDeclaration(
        palettes=tuple(names),
        default_palette=default,
        pygments=pygments,
    )


def _parse_pygments_table(
    section: Mapping[str, Any],
    names: Sequence[str],
    *,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Parse the optional ``[maatlog.pygments]`` table (Theme API 1.6).

    Keys must name declared palettes; values are Pygments style names. The
    table may cover only some palettes: the rest fall back to ``theme.conf``.
    """
    if "pygments" not in section:
        return ()
    raw: object = section["pygments"]
    if not isinstance(raw, Mapping):
        _invalid_manifest(
            field="pygments",
            value=raw,
            expected="a table of palette name to Pygments style name",
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
        )
    pairs: list[tuple[str, str]] = []
    for palette, style in cast(Mapping[str, Any], raw).items():
        if palette not in names:
            _invalid_manifest(
                field="pygments",
                value=palette,
                expected=f"one of {', '.join(names)}",
                theme_name=theme_name,
                inheritance_chain=inheritance_chain,
            )
        if not isinstance(style, str) or not style:
            _invalid_manifest(
                field="pygments",
                value=style,
                expected="a non-empty Pygments style name",
                theme_name=theme_name,
                inheritance_chain=inheritance_chain,
            )
        pairs.append((palette, style))
    return tuple(pairs)


def resolve_palette_declaration(
    theme_dirs: Sequence[str | Path],
    *,
    theme_name: str | None = None,
    inheritance_chain: Sequence[str] | None = None,
) -> PaletteDeclaration | None:
    """Return the first palette declaration on the theme inheritance chain.

    Themes need not declare palettes themselves; ``maatlog-default`` inherits
    the ``maatlog-base`` declaration this way. ``None`` means no theme on the
    chain declares palettes.
    """
    for directory in theme_dirs:
        manifest_path = Path(directory) / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        section = load_maatlog_section(
            manifest_path.read_text(encoding="utf-8"),
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
        )
        declaration = parse_palette_declaration(
            section,
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
        )
        if declaration is not None:
            return declaration
    return None


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
    declaration = resolve_palette_declaration(
        theme_dirs,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
    )
    if declaration is not None:
        _validate_palette_stylesheets(
            theme_dirs,
            declaration,
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            theme_api=manifest.api,
        )
        _validate_pygments_styles(
            declaration,
            theme_name=theme_name,
            inheritance_chain=inheritance_chain,
            theme_api=manifest.api,
        )


def resolve_palette(app: Sphinx) -> str | None:
    """Return the ``_static``-relative palette stylesheet to link, or ``None``.

    ``None`` when the builder is not full HTML, when the selected palette is
    the theme's default (its values already live in ``static/maatlog.css``),
    or when neither a palette nor a declaration is present.

    Raises:
        MaatlogBuildError: with ``maatlog.theme.palette-unsupported`` when a
            non-default palette is requested from a theme that declares none,
            or ``maatlog.theme.palette-unknown`` when the name is not offered
            by the selected theme.
    """
    if not is_html_theme_builder(app.builder):
        return None
    theme = getattr(app.builder, "theme", None)
    if theme is None:
        return None
    theme_dirs = theme.get_theme_dirs()
    if not theme_dirs:
        return None

    requested = MaatlogConfig.from_sphinx(app.config).palette
    inheritance_chain = tuple(Path(path).name for path in theme_dirs)
    theme_name = theme.name
    declaration = resolve_palette_declaration(
        theme_dirs,
        theme_name=theme_name,
        inheritance_chain=inheritance_chain,
    )

    if declaration is None:
        if requested is None:
            return None
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.theme.palette-unsupported",
                    message=(
                        "Selected theme offers no palettes"
                        + _theme_context_suffix(
                            inheritance_chain=inheritance_chain,
                            core_api=CORE_THEME_API,
                        )
                    ),
                    source=theme_name,
                    field="maatlog_palette",
                    value=requested,
                    expected="no maatlog_palette, or a theme declaring palettes",
                )
            ]
        )

    if requested is None or requested == declaration.default_palette:
        return None
    if requested not in declaration.palettes:
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.theme.palette-unknown",
                    message=(
                        f"Selected theme does not offer the palette {requested!r}"
                        + _theme_context_suffix(
                            inheritance_chain=inheritance_chain,
                            core_api=CORE_THEME_API,
                        )
                    ),
                    source=theme_name,
                    field="maatlog_palette",
                    value=requested,
                    expected=", ".join(declaration.palettes),
                )
            ]
        )
    return f"palettes/{requested}.css"


def resolve_pygments_style(app: Sphinx) -> str | None:
    """Return the Pygments style the selected palette declares, or ``None``.

    ``None`` means MaatLog leaves both highlighters alone: the builder is not
    full HTML, the site author set ``pygments_style`` in ``conf.py``, the theme
    declares no palettes, or the selected palette has no ``[maatlog.pygments]``
    entry. Palette-name validity is not re-checked here; ``resolve_palette``
    runs first on the same event and reports it.
    """
    if not is_html_theme_builder(app.builder):
        return None
    # An explicit conf.py choice wins whole: overriding only the light side
    # would emit a light/dark pair that does not belong together.
    if app.config.pygments_style is not None:
        return None
    theme = getattr(app.builder, "theme", None)
    if theme is None:
        return None
    theme_dirs = theme.get_theme_dirs()
    if not theme_dirs:
        return None

    inheritance_chain = tuple(Path(path).name for path in theme_dirs)
    declaration = resolve_palette_declaration(
        theme_dirs,
        theme_name=theme.name,
        inheritance_chain=inheritance_chain,
    )
    if declaration is None:
        return None
    requested = MaatlogConfig.from_sphinx(app.config).palette or declaration.default_palette
    return declaration.pygments_style_for(requested)


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


def _validate_palette_stylesheets(
    theme_dirs: Sequence[str | Path],
    declaration: PaletteDeclaration,
    *,
    theme_name: str,
    inheritance_chain: Sequence[str],
    theme_api: ThemeApiVersion,
) -> None:
    """Every declared non-default palette needs a stylesheet on the chain.

    The default palette lives in the theme's own ``static/maatlog.css``; giving
    it a palette file too would duplicate the same values in two places.
    """
    for name in declaration.palettes:
        if name == declaration.default_palette:
            continue
        relative = f"{PALETTES_RELATIVE}/{name}.css"
        if any((Path(directory) / relative).is_file() for directory in theme_dirs):
            continue
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.theme.palette-stylesheet-missing",
                    message=(
                        f"Declared palette {name!r} has no stylesheet"
                        + _theme_context_suffix(
                            inheritance_chain=inheritance_chain,
                            core_api=CORE_THEME_API,
                            theme_api=theme_api,
                        )
                    ),
                    source=theme_name,
                    field="palettes",
                    value=name,
                    expected=f"{relative} on the theme inheritance chain",
                )
            ]
        )


def _validate_pygments_styles(
    declaration: PaletteDeclaration,
    *,
    theme_name: str,
    inheritance_chain: Sequence[str],
    theme_api: ThemeApiVersion,
) -> None:
    """Every declared Pygments style must resolve (Theme API 1.6).

    All declared palettes are checked, not just the selected one: a theme
    author's typo should surface on their own build, not on a reader's.
    """
    for palette, style in declaration.pygments:
        try:
            _get_style_by_name(style)
        except ClassNotFound:
            raise MaatlogBuildError(
                [
                    Diagnostic(
                        code="maatlog.theme.pygments-style-unknown",
                        message=(
                            f"Palette {palette!r} declares an unknown Pygments style"
                            + _theme_context_suffix(
                                inheritance_chain=inheritance_chain,
                                core_api=CORE_THEME_API,
                                theme_api=theme_api,
                            )
                        ),
                        source=theme_name,
                        field="pygments",
                        value=style,
                        expected="a name resolvable by pygments.styles.get_style_by_name",
                    )
                ]
            ) from None


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

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TypeGuard, cast
from urllib.parse import urlsplit

from docutils import nodes
from pydantic import BaseModel, ConfigDict
from sphinx.application import Sphinx
from sphinx.util import logging

from ._myst_compat import read_typed_frontmatter
from .config import TAXONOMY_KEY_PATTERN, MaatlogConfig
from .domain import MaatlogDomain
from .errors import Diagnostic, MaatlogBuildError, format_diagnostic, redact_userinfo_in_text
from .images import (
    IMAGE_INVALID_EXPECTED,
    IMAGE_MISSING,
    IMAGE_MISSING_EXPECTED,
    ImageValidationError,
    validate_image_uri,
)
from .model import Post, parse_optional_datetime, publication_status

LOGGER = logging.getLogger(__name__)

KNOWN_KEYS = frozenset(
    {
        "maatlog-post",
        "maatlog-published-at",
        "maatlog-expires-at",
        "maatlog-slug",
        "maatlog-tags",
        "maatlog-categories",
        "maatlog-authors",
        "maatlog-excerpt",
        "maatlog-image",
        "maatlog-canonical-url",
        "maatlog-external-url",
    }
)
POST_ONLY_KEYS = KNOWN_KEYS - {"maatlog-post"}


class MetadataAdapter(StrEnum):
    RST = "rst"
    MYST = "myst"


class RawMetadataValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: object
    source: str
    line: int
    adapter: MetadataAdapter


class CollectionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    docname: str
    source_path: str
    source_root: Path
    source_text: str | None
    config: MaatlogConfig
    build_time: datetime
    note_dependency: Callable[[Path], None]
    # Register srcdir-relative path with Sphinx ``env.images`` after validation.
    register_image: Callable[[str], None] = lambda _path: None


def extract_post(document: nodes.document, context: CollectionContext) -> Post | None:
    fields = extract_leading_metadata(document, context.source_path, context.source_text)
    diagnostics = _unknown_key_diagnostics(fields)
    marker_diagnostic_count = len(diagnostics)
    marker = _normalize_post_marker(fields.get("maatlog-post"), diagnostics)

    if marker is not True:
        if len(diagnostics) == marker_diagnostic_count:
            diagnostics.extend(_without_post_diagnostics(fields))
        _raise_diagnostics(diagnostics)
        return None

    title = _document_title(document)
    if not title:
        diagnostics.append(
            _document_diagnostic(
                context,
                code="maatlog.metadata.required",
                message="A post requires a document title",
                field="title",
                expected="a non-empty Sphinx document title",
            )
        )

    slug = _normalize_slug(fields.get("maatlog-slug"), context, diagnostics)
    published_at = _normalize_datetime("maatlog-published-at", fields, context, diagnostics)
    expires_at = _normalize_datetime("maatlog-expires-at", fields, context, diagnostics)
    tags = _normalize_collection("maatlog-tags", fields, context.config.tags, diagnostics)
    categories = _normalize_collection("maatlog-categories", fields, context.config.categories, diagnostics)
    authors = _normalize_collection("maatlog-authors", fields, context.config.authors, diagnostics)
    excerpt = _normalize_optional_text("maatlog-excerpt", fields, diagnostics)
    image_uri = _normalize_image(fields, context, diagnostics)
    canonical_url = _normalize_url("maatlog-canonical-url", fields, diagnostics)
    external_url = _normalize_url("maatlog-external-url", fields, diagnostics)

    if expires_at is not None and published_at is None:
        diagnostics.append(
            _field_diagnostic(
                fields["maatlog-expires-at"],
                code="maatlog.metadata.combination",
                message="An expiry requires a publication time",
                field="maatlog-expires-at",
                expected="maatlog-published-at to be present",
            )
        )
    elif expires_at is not None and published_at is not None and expires_at <= published_at:
        diagnostics.append(
            _field_diagnostic(
                fields["maatlog-expires-at"],
                code="maatlog.datetime.order",
                message="Expiry must be after publication",
                field="maatlog-expires-at",
                expected="a datetime after maatlog-published-at",
            )
        )

    if external_url is not None and excerpt is None:
        diagnostics.append(
            _field_diagnostic(
                fields["maatlog-external-url"],
                code="maatlog.metadata.combination",
                message="An external post requires an excerpt",
                field="maatlog-external-url",
                expected="a non-empty maatlog-excerpt",
            )
        )

    _raise_diagnostics(diagnostics)
    assert title is not None
    assert slug is not None
    return Post(
        docname=context.docname,
        source_path=context.source_path,
        title=title,
        slug=slug,
        published_at=published_at,
        expires_at=expires_at,
        tags=tags,
        categories=categories,
        authors=authors,
        excerpt=excerpt,
        image_uri=image_uri,
        canonical_url=canonical_url,
        external_url=external_url,
        status=publication_status(published_at, expires_at, context.build_time),
    )


def extract_leading_metadata(
    document: nodes.document,
    source_path: str,
    source_text: str | None = None,
) -> dict[str, RawMetadataValue]:
    path = Path(source_path)
    adapter = MetadataAdapter.MYST if path.suffix.casefold() == ".md" else MetadataAdapter.RST
    if adapter is MetadataAdapter.MYST and source_text is not None:
        typed_fields = _read_myst_frontmatter(source_text, source_path)
        if typed_fields is not None:
            return typed_fields
    return _read_docinfo(document, source_path, adapter)


def collect_post(app: Sphinx, doctree: nodes.document) -> None:
    docname = app.env.current_document.docname
    source_path = str(app.env.doc2path(docname, base=True))
    source_text = _take_source(app, docname)
    context = CollectionContext(
        docname=docname,
        source_path=source_path,
        source_root=Path(app.srcdir),
        source_text=source_text,
        config=MaatlogConfig.from_sphinx(app.config),
        build_time=cast(datetime, app.__dict__["_maatlog_build_time"]),
        note_dependency=lambda path: app.env.note_dependency(path),
        register_image=lambda path: _register_env_image(app, docname, path),
    )
    try:
        post = extract_post(doctree, context)
    except MaatlogBuildError as error:
        for diagnostic in error.diagnostics:
            location: tuple[str, int | None] | None = None
            if diagnostic.source is not None:
                location = (diagnostic.source, diagnostic.line)
            LOGGER.error(format_diagnostic(diagnostic), location=location)
        raise

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    if post is None:
        domain.clear_doc(docname)
    else:
        domain.note_post(post)


def _register_env_image(app: Sphinx, docname: str, relative_path: str) -> None:
    """Register a validated representative image with Sphinx's image pipeline."""
    app.env.images.add_file(docname, relative_path)


def capture_source(app: Sphinx, docname: str, source: list[str]) -> None:
    sources = cast(dict[str, list[str]], app.__dict__.setdefault("_maatlog_sources_by_docname", {}))
    sources[docname] = source


def cleanup_sources(app: Sphinx, exception: Exception | None) -> None:
    del exception
    app.__dict__.pop("_maatlog_sources_by_docname", None)


def _take_source(app: Sphinx, docname: str) -> str | None:
    sources = cast(dict[str, list[str]], app.__dict__.setdefault("_maatlog_sources_by_docname", {}))
    source = sources.pop(docname, None)
    return source[0] if source is not None else None


def _read_myst_frontmatter(source_text: str, source_path: str) -> dict[str, RawMetadataValue] | None:
    topmatter = read_typed_frontmatter(source_text)
    if topmatter is None:
        return None
    return {
        key: RawMetadataValue(
            value=value,
            source=source_path,
            line=line,
            adapter=MetadataAdapter.MYST,
        )
        for key, (value, line) in topmatter.items()
    }


def _read_docinfo(
    document: nodes.document,
    source_path: str,
    adapter: MetadataAdapter,
) -> dict[str, RawMetadataValue]:
    metadata_node: nodes.Element | None = next(
        (child for child in document.children if isinstance(child, nodes.docinfo)), None
    )
    if metadata_node is None:
        first_section = next((child for child in document.children if isinstance(child, nodes.section)), None)
        if first_section is not None and len(first_section.children) > 1:
            candidate = first_section.children[1]
            if isinstance(first_section.children[0], nodes.title) and isinstance(candidate, nodes.field_list):
                metadata_node = candidate
    if metadata_node is None:
        return {}
    fields: dict[str, RawMetadataValue] = {}
    for child in metadata_node.children:
        if not isinstance(child, nodes.field) or len(child) != 2:
            continue
        name = child[0].astext()
        if not name.startswith("maatlog-"):
            continue
        fields[name] = RawMetadataValue(
            value=child[1].astext(),
            source=child.source if child.source and Path(child.source).exists() else source_path,
            line=child.line if child.line is not None and child.line > 0 else 1,
            adapter=adapter,
        )
    return fields


def _unknown_key_diagnostics(fields: Mapping[str, RawMetadataValue]) -> list[Diagnostic]:
    return [
        _field_diagnostic(
            raw,
            code="maatlog.metadata.unknown",
            message="Unknown MaatLog metadata key",
            field=name,
            expected="a documented MaatLog metadata key",
        )
        for name, raw in fields.items()
        if name not in KNOWN_KEYS
    ]


def _without_post_diagnostics(fields: Mapping[str, RawMetadataValue]) -> list[Diagnostic]:
    return [
        _field_diagnostic(
            raw,
            code="maatlog.metadata.without-post",
            message="Post metadata requires maatlog-post: true",
            field=name,
            expected="maatlog-post: true",
        )
        for name, raw in fields.items()
        if name in POST_ONLY_KEYS
    ]


def _normalize_post_marker(raw: RawMetadataValue | None, diagnostics: list[Diagnostic]) -> bool:
    if raw is None:
        return False
    if isinstance(raw.value, bool):
        return raw.value
    if (
        raw.adapter is MetadataAdapter.RST
        and isinstance(raw.value, str)
        and raw.value.strip().casefold() in {"true", "false"}
    ):
        return raw.value.strip().casefold() == "true"
    diagnostics.append(
        _field_diagnostic(
            raw,
            code="maatlog.metadata.type",
            message="Invalid post marker type",
            field="maatlog-post",
            expected="a boolean or the case-insensitive text true or false",
        )
    )
    return False


def _normalize_slug(
    raw: RawMetadataValue | None,
    context: CollectionContext,
    diagnostics: list[Diagnostic],
) -> str | None:
    if raw is None:
        diagnostics.append(
            _document_diagnostic(
                context,
                code="maatlog.metadata.required",
                message="A post requires a slug",
                field="maatlog-slug",
                expected="[a-z0-9][a-z0-9._-]*",
            )
        )
        return None
    if not isinstance(raw.value, str):
        diagnostics.append(_type_diagnostic(raw, "maatlog-slug", "a string"))
        return None
    if TAXONOMY_KEY_PATTERN.fullmatch(raw.value) is None:
        diagnostics.append(
            _field_diagnostic(
                raw,
                code="maatlog.slug.invalid",
                message="Invalid post slug",
                field="maatlog-slug",
                expected="[a-z0-9][a-z0-9._-]*",
            )
        )
        return None
    return raw.value


def _normalize_datetime(
    name: str,
    fields: Mapping[str, RawMetadataValue],
    context: CollectionContext,
    diagnostics: list[Diagnostic],
) -> datetime | None:
    raw = fields.get(name)
    if raw is None:
        return None
    if isinstance(raw.value, datetime):
        value = raw.value.isoformat()
    elif isinstance(raw.value, str):
        value = raw.value
    else:
        diagnostics.append(_type_diagnostic(raw, name, "an ISO 8601 datetime string"))
        return None
    try:
        return parse_optional_datetime(value, context.config.timezone)
    except MaatlogBuildError as error:
        diagnostics.extend(
            item.model_copy(update={"source": raw.source, "line": raw.line, "field": name, "value": repr(raw.value)})
            for item in error.diagnostics
        )
        return None


def _normalize_collection(
    name: str,
    fields: Mapping[str, RawMetadataValue],
    configured: Mapping[str, str] | None,
    diagnostics: list[Diagnostic],
) -> tuple[str, ...]:
    raw = fields.get(name)
    if raw is None:
        return ()
    values: Sequence[object]
    if isinstance(raw.value, str):
        values = raw.value.split(",")
    elif _is_metadata_sequence(raw.value):
        values = raw.value
    else:
        diagnostics.append(_type_diagnostic(raw, name, "a string or sequence of strings"))
        return ()

    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            diagnostics.append(_type_diagnostic(raw, name, "a string or sequence of strings"))
            continue
        taxonomy_id = value.strip()
        if not taxonomy_id or TAXONOMY_KEY_PATTERN.fullmatch(taxonomy_id) is None:
            diagnostics.append(
                _field_diagnostic(
                    raw,
                    code="maatlog.taxonomy-id.invalid",
                    message="Invalid taxonomy ID",
                    field=name,
                    expected="[a-z0-9][a-z0-9._-]*",
                    value=repr(value),
                )
            )
            continue
        if configured is not None and taxonomy_id not in configured:
            diagnostics.append(
                _field_diagnostic(
                    raw,
                    code="maatlog.taxonomy.undefined",
                    message="Taxonomy ID is not configured",
                    field=name,
                    expected="an ID present in the corresponding MaatLog taxonomy config",
                    value=repr(taxonomy_id),
                )
            )
            continue
        if taxonomy_id not in normalized:
            normalized.append(taxonomy_id)
    return tuple(normalized)


def _normalize_optional_text(
    name: str,
    fields: Mapping[str, RawMetadataValue],
    diagnostics: list[Diagnostic],
) -> str | None:
    raw = fields.get(name)
    if raw is None:
        return None
    if not isinstance(raw.value, str):
        diagnostics.append(_type_diagnostic(raw, name, "a string"))
        return None
    value = raw.value.strip()
    if not value:
        diagnostics.append(
            _field_diagnostic(
                raw,
                code="maatlog.metadata.value",
                message="Metadata text must not be empty",
                field=name,
                expected="a non-empty string",
            )
        )
        return None
    return value


def _normalize_image(
    fields: Mapping[str, RawMetadataValue],
    context: CollectionContext,
    diagnostics: list[Diagnostic],
) -> str | None:
    name = "maatlog-image"
    raw = fields.get(name)
    if raw is None:
        return None
    if not isinstance(raw.value, str):
        diagnostics.append(_type_diagnostic(raw, name, "a source-relative local URI"))
        return None
    uri = raw.value.strip()
    try:
        candidate = validate_image_uri(uri, source=Path(context.source_path), srcdir=context.source_root)
    except ImageValidationError as error:
        expected = IMAGE_MISSING_EXPECTED if error.code == IMAGE_MISSING else IMAGE_INVALID_EXPECTED
        diagnostics.append(
            _field_diagnostic(
                raw,
                code=error.code,
                message=error.message,
                field=name,
                expected=expected,
            )
        )
        return None
    # Sphinx image maps use paths relative to srcdir (same keys as ImageCollector).
    relative = candidate.relative_to(context.source_root.resolve()).as_posix()
    context.note_dependency(candidate)
    context.register_image(relative)
    return relative


def _is_metadata_sequence(value: object) -> TypeGuard[list[object] | tuple[object, ...]]:
    return isinstance(value, (list, tuple))


def _normalize_url(
    name: str,
    fields: Mapping[str, RawMetadataValue],
    diagnostics: list[Diagnostic],
) -> str | None:
    raw = fields.get(name)
    if raw is None:
        return None
    if not isinstance(raw.value, str):
        diagnostics.append(_type_diagnostic(raw, name, "an absolute HTTP or HTTPS URL"))
        return None
    value = raw.value.strip()
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
        or any(character.isspace() for character in value)
    ):
        diagnostics.append(
            _field_diagnostic(
                raw,
                code="maatlog.url.invalid",
                message="Invalid absolute URL",
                field=name,
                expected="an absolute HTTP or HTTPS URL without userinfo or a fragment",
                value=repr(redact_userinfo_in_text(value)),
            )
        )
        return None
    return value


def _document_title(document: nodes.document) -> str | None:
    title: nodes.title | None = None
    for child in document.children:
        if isinstance(child, nodes.title):
            title = child
            break
        if isinstance(child, nodes.section) and child.children and isinstance(child.children[0], nodes.title):
            title = child.children[0]
            break
    if title is None:
        return None
    value = title.astext().strip()
    return value or None


def _type_diagnostic(raw: RawMetadataValue, field: str, expected: str) -> Diagnostic:
    return _field_diagnostic(
        raw,
        code="maatlog.metadata.type",
        message="Invalid metadata type",
        field=field,
        expected=expected,
    )


def _field_diagnostic(
    raw: RawMetadataValue,
    *,
    code: str,
    message: str,
    field: str,
    expected: str,
    value: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        source=raw.source,
        line=raw.line,
        field=field,
        value=repr(raw.value) if value is None else value,
        expected=expected,
    )


def _document_diagnostic(
    context: CollectionContext,
    *,
    code: str,
    message: str,
    field: str,
    expected: str,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        source=context.source_path,
        line=1,
        field=field,
        expected=expected,
    )


def _raise_diagnostics(diagnostics: Sequence[Diagnostic]) -> None:
    if diagnostics:
        raise MaatlogBuildError(diagnostics)

from datetime import UTC, datetime
from pathlib import Path

import pytest
from docutils import nodes
from docutils.utils import new_document
from pydantic import ValidationError

from maatlog.config import MaatlogConfig
from maatlog.errors import MaatlogBuildError
from maatlog.metadata import CollectionContext, MetadataAdapter, RawMetadataValue, extract_post


def test_internal_adapter_values_are_frozen_pydantic_models() -> None:
    raw = RawMetadataValue(value=True, source="post.md", line=2, adapter=MetadataAdapter.MYST)

    with pytest.raises(ValidationError, match="Instance is frozen"):
        raw.line = 3
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RawMetadataValue.model_validate(
            {"value": True, "source": "post.md", "line": 2, "adapter": "myst", "extra": True}
        )


def test_extract_post_normalizes_and_stably_deduplicates_rst_lists(tmp_path: Path) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")
    document = _rst_document(
        source,
        {
            "maatlog-post": "TrUe",
            "maatlog-slug": "hello",
            "maatlog-tags": " sphinx, python, sphinx ",
            "maatlog-categories": "engineering",
            "maatlog-authors": "alice",
        },
    )

    post = extract_post(document, _context(source))

    assert post is not None
    assert post.tags == ("sphinx", "python")
    assert post.categories == ("engineering",)
    assert post.authors == ("alice",)


def test_extract_post_rejects_ids_absent_from_configured_taxonomy(tmp_path: Path) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")
    document = _rst_document(
        source,
        {
            "maatlog-post": "true",
            "maatlog-slug": "hello",
            "maatlog-tags": "unknown",
        },
    )
    config = MaatlogConfig.from_values({"maatlog_tags": {"known": "Known"}})

    with pytest.raises(MaatlogBuildError) as error:
        extract_post(document, _context(source, config=config))

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.taxonomy.undefined"
    assert diagnostic.field == "maatlog-tags"
    assert diagnostic.source == str(source)
    assert diagnostic.line == 3


def _context(source: Path, *, config: MaatlogConfig | None = None) -> CollectionContext:
    return CollectionContext(
        docname="post",
        source_path=str(source),
        source_root=source.parent,
        source_text=None,
        config=config or MaatlogConfig.from_values({}),
        build_time=datetime(2026, 8, 1, tzinfo=UTC),
        note_dependency=lambda _: None,
    )


def _rst_document(source: Path, fields: dict[str, str]) -> nodes.document:
    document = new_document(str(source))
    document["source"] = str(source)
    docinfo = nodes.docinfo()
    for line, (name, value) in enumerate(fields.items(), start=1):
        field = nodes.field()
        field.source = str(source)
        field.line = line
        field += nodes.field_name(name, name)
        field += nodes.field_body(value, nodes.paragraph(value, value))
        docinfo += field
    section = nodes.section(ids=["title"])
    section.source = str(source)
    section.line = len(fields) + 2
    section += nodes.title("Title", "Title")
    document += docinfo
    document += section
    return document

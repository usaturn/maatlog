from collections.abc import MutableMapping
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError

from maatlog.config import MaatlogConfig
from maatlog.errors import MaatlogBuildError


def test_config_defaults():
    config = MaatlogConfig.from_values({})

    assert config.timezone.key == "UTC"
    assert config.archive_docname == "blog"
    assert config.page_size == 10
    assert config.generate_feeds is True
    assert config.feed_taxonomies == ("tag", "category", "author", "month")
    assert config.feed_limit == 20


def test_invalid_values_are_aggregated():
    with pytest.raises(MaatlogBuildError) as error:
        MaatlogConfig.from_values(
            {
                "maatlog_page_size": 0,
                "maatlog_archive_docname": "../blog/",
            }
        )

    assert [item.code for item in error.value.diagnostics] == [
        "maatlog.config.invalid",
        "maatlog.config.invalid",
    ]


def test_feed_taxonomies_are_stably_deduplicated():
    config = MaatlogConfig.from_values({"maatlog_feed_taxonomies": ("tag", "tag", "month", "tag", "author")})

    assert config.feed_taxonomies == ("tag", "month", "author")


def test_taxonomy_mapping_invalid_keys_and_labels_are_aggregated():
    with pytest.raises(MaatlogBuildError) as error:
        MaatlogConfig.from_values({"maatlog_tags": {"Invalid Key": "", "UPPER": "Label"}})

    assert [item.field for item in error.value.diagnostics] == [
        "maatlog_tags",
        "maatlog_tags",
        "maatlog_tags",
    ]


def test_archive_docname_rejects_empty_path_segments():
    with pytest.raises(MaatlogBuildError) as error:
        MaatlogConfig.from_values({"maatlog_archive_docname": "blog//tag"})

    assert error.value.diagnostics[0].field == "maatlog_archive_docname"


def test_config_copies_taxonomy_mappings_to_immutable_mappings():
    tags = {"tag": "Tag"}

    config = MaatlogConfig.from_values({"maatlog_tags": tags})
    tags["new-tag"] = "New tag"

    assert dict(config.tags or {}) == {"tag": "Tag"}
    with pytest.raises(TypeError):
        assert config.tags is not None
        cast(MutableMapping[str, str], config.tags)["new-tag"] = "New tag"


def test_config_is_a_frozen_pydantic_model():
    config = MaatlogConfig.from_values({})

    assert isinstance(config, BaseModel)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        field_name = "page_size"
        setattr(config, field_name, 20)


def test_config_forbids_extra_fields():
    config = MaatlogConfig.from_values({})
    values = config.model_dump()
    values["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MaatlogConfig.model_validate(values)


def test_tagline_and_home_docname_default_to_none() -> None:
    config = MaatlogConfig.from_values({})
    assert config.tagline is None
    assert config.home_docname is None


def test_tagline_accepts_a_non_empty_string() -> None:
    config = MaatlogConfig.from_values({"maatlog_tagline": "Notes on Sphinx"})
    assert config.tagline == "Notes on Sphinx"


@pytest.mark.parametrize("value", ["", "   ", 42, ["a"]])
def test_tagline_rejects_empty_and_non_strings(value: object) -> None:
    with pytest.raises(MaatlogBuildError) as caught:
        MaatlogConfig.from_values({"maatlog_tagline": value})
    codes = {diagnostic.code for diagnostic in caught.value.diagnostics}
    fields = {diagnostic.field for diagnostic in caught.value.diagnostics}
    assert codes == {"maatlog.config.invalid"}
    assert fields == {"maatlog_tagline"}


def test_home_docname_accepts_a_relative_docname() -> None:
    config = MaatlogConfig.from_values({"maatlog_home_docname": "index"})
    assert config.home_docname == "index"


@pytest.mark.parametrize("value", ["", "/index", "index/", "a//b", "../index", 1])
def test_home_docname_rejects_invalid_values(value: object) -> None:
    with pytest.raises(MaatlogBuildError) as caught:
        MaatlogConfig.from_values({"maatlog_home_docname": value})
    fields = {diagnostic.field for diagnostic in caught.value.diagnostics}
    assert fields == {"maatlog_home_docname"}

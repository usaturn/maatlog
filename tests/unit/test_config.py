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

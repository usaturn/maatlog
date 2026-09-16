from __future__ import annotations

from typing import Any

import pytest

from maatlog.config import CONFIG_VALUES, MaatlogConfig
from maatlog.errors import MaatlogBuildError

FIELD = "maatlog_responsive_image_widths"
EXPECTED = "a non-empty sequence of positive integers"


def build(**overrides: Any) -> MaatlogConfig:
    return MaatlogConfig.from_values(overrides)


def test_defaults_keep_responsive_images_off() -> None:
    config = build()
    assert config.responsive_images is False
    assert config.responsive_image_widths == (480, 768, 960, 1200, 1600)


def test_config_values_declare_html_rebuild() -> None:
    assert CONFIG_VALUES["maatlog_responsive_images"] == (False, "html")
    assert CONFIG_VALUES[FIELD] == ((480, 768, 960, 1200, 1600), "html")


def test_widths_accept_list_and_normalize() -> None:
    config = build(**{FIELD: [1200, 480, 480, 768]})
    assert config.responsive_image_widths == (480, 768, 1200)


@pytest.mark.parametrize(
    "value",
    [
        "480,768",
        b"480",
        480,
        None,
        (),
        [],
        [True],
        [False, 480],
        [480.0],
        ["480"],
        [0],
        [-480],
        [480, 0],
    ],
)
def test_widths_reject_invalid_values(value: Any) -> None:
    with pytest.raises(MaatlogBuildError) as error:
        build(**{FIELD: value})
    diagnostics = error.value.diagnostics
    assert [item.code for item in diagnostics] == ["maatlog.config.invalid"] * len(diagnostics)
    assert {item.field for item in diagnostics} == {FIELD}
    assert {item.expected for item in diagnostics} == {EXPECTED}


def test_responsive_images_rejects_non_bool() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        build(maatlog_responsive_images=1)
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.field == "maatlog_responsive_images"
    assert diagnostic.expected == "a boolean"


def test_config_errors_aggregate() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        build(maatlog_responsive_images="yes", **{FIELD: [0]})
    fields = {item.field for item in error.value.diagnostics}
    assert fields == {"maatlog_responsive_images", FIELD}

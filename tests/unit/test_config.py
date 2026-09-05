from __future__ import annotations

from collections.abc import MutableMapping
from typing import cast

import pytest
from pydantic import BaseModel, ValidationError

from maatlog.config import CONFIG_VALUES, MaatlogConfig
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


def test_palette_defaults_to_none() -> None:
    # None は「そのテーマの default_palette を使う」の意味。"indigo" を
    # リテラルの既定にすると、既定名の異なる第三者テーマと食い違う。
    assert CONFIG_VALUES["maatlog_palette"] == (None, "html")
    assert MaatlogConfig.from_values({}).palette is None


def test_palette_accepts_a_lowercase_name() -> None:
    assert MaatlogConfig.from_values({"maatlog_palette": "neon"}).palette == "neon"


@pytest.mark.parametrize("value", ["", "Neon", "../evil", "neon/x", 1, True, ["neon"]])
def test_invalid_palette_is_rejected(value: object) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.config.invalid") as error:
        MaatlogConfig.from_values({"maatlog_palette": value})

    assert error.value.diagnostics[0].field == "maatlog_palette"


def test_author_profiles_default_to_none() -> None:
    assert CONFIG_VALUES["maatlog_author_profiles"] == (None, "env")
    assert MaatlogConfig.from_values({}).author_profiles is None


def test_author_profiles_are_accepted() -> None:
    config = MaatlogConfig.from_values(
        {
            "maatlog_authors": {"alice": "Alice"},
            "maatlog_author_profiles": {
                "alice": {"links": [{"type": "GitHub", "url": "https://github.com/alice"}]},
            },
        }
    )

    assert config.author_profiles is not None
    link = config.author_profiles["alice"].links[0]
    assert (link.type, link.label, link.icon) == ("github", "GitHub", "github")


def test_author_profiles_do_not_require_a_matching_display_name() -> None:
    """maatlog_authors は None を許すため、slug の相互参照は検証しない。"""
    config = MaatlogConfig.from_values({"maatlog_author_profiles": {"alice": {"links": []}}})

    assert config.author_profiles is not None
    assert config.author_profiles["alice"].links == ()


def test_author_profiles_mapping_is_frozen() -> None:
    config = MaatlogConfig.from_values({"maatlog_author_profiles": {"alice": {"links": []}}})

    assert config.author_profiles is not None
    with pytest.raises(TypeError):
        cast(MutableMapping[str, object], config.author_profiles)["bob"] = {}


@pytest.mark.parametrize("value", ["alice", 1, ["alice"]])
def test_non_mapping_author_profiles_are_rejected(value: object) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.config.invalid") as error:
        MaatlogConfig.from_values({"maatlog_author_profiles": value})

    assert error.value.diagnostics[0].field == "maatlog_author_profiles"


@pytest.mark.parametrize("slug", ["Alice", "", "-alice", "alice/bob"])
def test_invalid_author_profile_slugs_are_rejected(slug: str) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.config.invalid") as error:
        MaatlogConfig.from_values({"maatlog_author_profiles": {slug: {"links": []}}})

    assert error.value.diagnostics[0].field == "maatlog_author_profiles"


def test_invalid_author_link_is_rejected() -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.author.link-invalid") as error:
        MaatlogConfig.from_values(
            {"maatlog_author_profiles": {"alice": {"links": [{"type": "github", "url": "/alice"}]}}}
        )

    assert error.value.diagnostics[0].field == "maatlog_author_profiles.alice.links[0].url"


def test_unknown_author_profile_key_is_rejected() -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.config.invalid") as error:
        MaatlogConfig.from_values({"maatlog_author_profiles": {"alice": {"bio": "Alice"}}})

    assert error.value.diagnostics[0].field == "maatlog_author_profiles.alice"


def test_top_image_title_font_defaults_to_none() -> None:
    config = MaatlogConfig.from_values({})
    assert config.top_image_title_font is None


def test_top_image_title_font_accepts_font_family_string() -> None:
    config = MaatlogConfig.from_values({"maatlog_top_image_title_font": "Georgia, serif"})
    assert config.top_image_title_font == "Georgia, serif"


def test_top_image_title_font_accepts_none_explicitly() -> None:
    config = MaatlogConfig.from_values({"maatlog_top_image_title_font": None})
    assert config.top_image_title_font is None


def test_top_image_title_font_accepts_quoted_font_family() -> None:
    """引用符付きのフォントスタックは CSS として正当なので受理する。"""
    config = MaatlogConfig.from_values({"maatlog_top_image_title_font": '"Noto Sans JP", serif'})
    assert config.top_image_title_font == '"Noto Sans JP", serif'


@pytest.mark.parametrize(
    "value",
    [
        'X; } body { display: none; } .y { font-family: "z"',
        "Georgia</style><script>alert(1)</script>",
        "Georgia; --injected: 1",
        "Georgia /* comment */, serif",
        "Georgia\\26 , serif",
    ],
)
def test_top_image_title_font_rejects_css_control_characters(value: str) -> None:
    """``<style>`` へ素通しするため、宣言や要素から抜け出せる値は拒否する。"""
    with pytest.raises(MaatlogBuildError) as error:
        MaatlogConfig.from_values({"maatlog_top_image_title_font": value})

    assert error.value.diagnostics[0].field == "maatlog_top_image_title_font"


def test_config_accepts_full_author_profile() -> None:
    config = MaatlogConfig.from_values(
        {
            "maatlog_authors": {"alice": "Alice Anderson"},
            "maatlog_author_profiles": {
                "alice": {
                    "role": "Editor",
                    "avatar": "authors/alice.png",
                    "bio_short": "Hello.",
                    "interests": ["Python"],
                    "links": [{"type": "github", "url": "https://github.com/alice"}],
                    "featured_posts": ["one"],
                    "about_docname": "authors/alice",
                }
            },
        }
    )

    assert config.author_profiles is not None
    profile = config.author_profiles["alice"]
    assert profile.interests == ("Python",)
    assert profile.featured_posts == ("one",)
    assert profile.about_docname == "authors/alice"


def test_default_author_accepts_a_lowercase_author_id() -> None:
    config = MaatlogConfig.from_values({"maatlog_authors": {"alice": "Alice"}, "maatlog_default_author": "alice"})

    assert config.default_author == "alice"


def test_default_author_defaults_to_none() -> None:
    assert MaatlogConfig.from_values({}).default_author is None


@pytest.mark.parametrize("value", ["Alice", "", " ", 1, ["alice"]])
def test_default_author_rejects_a_malformed_value(value: object) -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        MaatlogConfig.from_values({"maatlog_default_author": value})

    assert [item.code for item in excinfo.value.diagnostics] == ["maatlog.config.invalid"]
    assert excinfo.value.diagnostics[0].field == "maatlog_default_author"


def test_default_author_must_exist_in_maatlog_authors() -> None:
    with pytest.raises(MaatlogBuildError) as excinfo:
        MaatlogConfig.from_values({"maatlog_authors": {"alice": "Alice"}, "maatlog_default_author": "carol"})

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "maatlog.config.invalid"
    assert diagnostic.field == "maatlog_default_author"
    assert diagnostic.expected == "an author id present in maatlog_authors"


def test_default_author_is_not_checked_when_authors_are_dynamic() -> None:
    # maatlog_authors が None のとき author id は投稿から登録されるため、
    # 静的な集合が無く、存在検査はできない。
    config = MaatlogConfig.from_values({"maatlog_default_author": "carol"})

    assert config.default_author == "carol"


def test_content_width_defaults_to_none() -> None:
    config = MaatlogConfig.from_values({})
    assert config.content_width is None


def test_content_width_accepts_none_explicitly() -> None:
    config = MaatlogConfig.from_values({"maatlog_content_width": None})
    assert config.content_width is None


@pytest.mark.parametrize(
    "value",
    [
        "100%",
        "72rem",
        "80rem",
        "clamp(42rem, 70vw, 90rem)",
        "min(90vw, 100rem)",
        "calc(100% - 2rem)",
        "var(--custom-width)",
        "none",
    ],
)
def test_content_width_accepts_css_width_values(value: str) -> None:
    """CSS の max-width として妥当な書き方は素通しする。"""
    config = MaatlogConfig.from_values({"maatlog_content_width": value})
    assert config.content_width == value


@pytest.mark.parametrize(
    "value",
    [
        "60rem; color: red",
        "60rem} body { display: none",
        "60rem</style><script>alert(1)</script>",
        "60rem /* comment */",
        "60rem\\26 ",
        "",
        "   ",
    ],
)
def test_content_width_rejects_values_that_escape_the_declaration(value: str) -> None:
    """``<style>`` へ素通しするため、宣言や要素から抜け出せる値は拒否する。"""
    with pytest.raises(MaatlogBuildError) as error:
        MaatlogConfig.from_values({"maatlog_content_width": value})

    assert error.value.diagnostics[0].field == "maatlog_content_width"


@pytest.mark.parametrize("value", [72, 72.0, True, [], {}])
def test_content_width_rejects_non_strings(value: object) -> None:
    with pytest.raises(MaatlogBuildError) as error:
        MaatlogConfig.from_values({"maatlog_content_width": value})

    assert error.value.diagnostics[0].field == "maatlog_content_width"

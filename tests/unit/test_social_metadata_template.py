from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import HtmlPage
from jinja2 import Environment, FileSystemLoader, select_autoescape
from social_metadata import (
    JsonLdCollector,
    assert_crawler_urls_are_absolute,
    assert_no_social_metadata,
    json_ld_objects,
    open_graph_values,
    twitter_values,
)

from maatlog.social_metadata import (
    OpenGraphPropertyView,
    SocialMetadataView,
    TwitterCardPropertyView,
    serialize_json_ld,
)
from maatlog.views import MaatlogTemplateContext, as_template_mapping

#: Turns one view into the ``maatlog.metadata`` value the template receives.
MetadataShape = Callable[[SocialMetadataView], object]


def _view_shape(metadata: SocialMetadataView) -> object:
    """The dataclass itself, as a standalone theme or a unit test would pass it."""
    return metadata


def _mapping_shape(metadata: SocialMetadataView) -> object:
    """What a real build passes: ``as_template_mapping`` output, i.e. dicts and tuples."""
    return as_template_mapping(replace(MaatlogTemplateContext(), metadata=metadata))["metadata"]


#: Both shapes must render identically, so the partial is never pinned to the attribute
#: access form alone (``inject_maatlog_page_context`` only ever sends the mapping form).
METADATA_SHAPES = pytest.mark.parametrize("shape", [_view_shape, _mapping_shape], ids=["view", "mapping"])


def render_metadata(metadata: SocialMetadataView, shape: MetadataShape = _view_shape) -> HtmlPage:
    theme_root = Path(__file__).resolve().parents[2] / "src" / "maatlog" / "themes" / "maatlog-base"
    environment = Environment(loader=FileSystemLoader(theme_root), autoescape=select_autoescape())
    template = environment.get_template("maatlog/components/social-metadata.html")
    return HtmlPage(template.render(maatlog={"metadata": shape(metadata)}))


@METADATA_SHAPES
def test_social_metadata_partial_preserves_values_and_escapes_html(shape: MetadataShape) -> None:
    page = render_metadata(
        SocialMetadataView(
            open_graph=(
                OpenGraphPropertyView(property="article:tag", content="one"),
                OpenGraphPropertyView(property="article:tag", content="two"),
            ),
            twitter=(TwitterCardPropertyView(name="twitter:title", content='Title "<&'),),
            json_ld=serialize_json_ld({"headline": "</script> 日本語"}),
        ),
        shape,
    )

    assert open_graph_values(page, "article:tag") == ["one", "two"]
    assert twitter_values(page, "twitter:title") == ['Title "<&']
    assert json_ld_objects(page) == [{"headline": "</script> 日本語"}]
    assert page.text.lower().count("</script>") == 1


@METADATA_SHAPES
def test_empty_metadata_renders_no_social_metadata(shape: MetadataShape) -> None:
    page = render_metadata(SocialMetadataView(), shape)

    assert_no_social_metadata(page)
    assert page.text == ""


def test_json_ld_collector_concatenates_chunks_and_collects_each_script() -> None:
    parser = JsonLdCollector()
    parser.feed('<script type="application/ld+json">')
    parser.handle_data('{"headline":')
    parser.handle_data('"日本語"}')
    parser.feed('</script><script type="application/ld+json">{}</script>')
    parser.close()

    assert parser.bodies == ['{"headline":"日本語"}', "{}"]


def test_json_ld_objects_selects_only_exact_json_ld_type() -> None:
    page = HtmlPage(
        '<script type="application/json">invalid</script>'
        '<script type="application/ld+json; charset=utf-8">invalid</script>'
        '<script type="application/ld+json">{"first": 1}</script>'
        '<script type="application/ld+json">{"second": 2}</script>'
    )

    assert json_ld_objects(page) == [{"first": 1}, {"second": 2}]


def test_json_ld_collector_rejects_nested_capture() -> None:
    parser = JsonLdCollector()
    parser.handle_starttag("script", [("type", "application/ld+json")])

    with pytest.raises(AssertionError, match="nested JSON-LD script"):
        parser.handle_starttag("script", [("type", "application/ld+json")])


def test_json_ld_objects_rejects_unterminated_script() -> None:
    with pytest.raises(AssertionError, match="unterminated JSON-LD script"):
        json_ld_objects(HtmlPage('<script type="application/ld+json">{}'))


@METADATA_SHAPES
def test_crawler_url_check_rejects_relative_url_nested_under_image(shape: MetadataShape) -> None:
    dict_nested = render_metadata(
        SocialMetadataView(
            json_ld=serialize_json_ld({"image": {"url": "relative.png"}}),
        ),
        shape,
    )
    list_nested = render_metadata(
        SocialMetadataView(
            json_ld=serialize_json_ld({"image": [{"url": "relative.png"}]}),
        ),
        shape,
    )

    with pytest.raises(AssertionError, match="relative.png"):
        assert_crawler_urls_are_absolute(dict_nested)
    with pytest.raises(AssertionError, match="relative.png"):
        assert_crawler_urls_are_absolute(list_nested)

import json
import re
from dataclasses import FrozenInstanceError

import pytest

from maatlog.social_metadata import (
    OpenGraphPropertyView,
    SocialMetadataView,
    TwitterCardPropertyView,
    serialize_json_ld,
)
from maatlog.views import MaatlogTemplateContext, as_template_mapping, empty_context

#: The characters that must never reach a ``<script>`` element raw. This list is the
#: specification: ``serialize_json_ld()`` has to escape every one of them and
#: ``SocialMetadataView`` has to reject every one of them, so the two cannot drift apart.
SCRIPT_UNSAFE_CHARACTERS = ("<", ">", "&", "\u2028", "\u2029")


def test_social_metadata_view_preserves_attribute_kinds_and_order() -> None:
    metadata = SocialMetadataView(
        open_graph=(
            OpenGraphPropertyView(property="og:title", content="Title"),
            OpenGraphPropertyView(property="article:tag", content="one"),
            OpenGraphPropertyView(property="article:tag", content="two"),
        ),
        twitter=(TwitterCardPropertyView(name="twitter:card", content="summary"),),
        json_ld='{"@type":"Thing"}',
    )
    assert [item.property for item in metadata.open_graph] == ["og:title", "article:tag", "article:tag"]
    assert metadata.twitter[0].name == "twitter:card"
    with pytest.raises(FrozenInstanceError):
        metadata.json_ld = None  # type: ignore[misc]


def test_json_ld_rejects_raw_script_markup() -> None:
    # The shared partial renders json_ld with |safe, so a raw </script> would escape the
    # script element. Only serialize_json_ld() output may reach this field.
    with pytest.raises(ValueError, match="serialize_json_ld"):
        SocialMetadataView(json_ld='{"headline":"</script><script>alert(1)"}')


@pytest.mark.parametrize("character", SCRIPT_UNSAFE_CHARACTERS)
def test_json_ld_rejects_every_script_unsafe_character(character: str) -> None:
    with pytest.raises(ValueError, match=f"U\\+{ord(character):04X}"):
        SocialMetadataView(json_ld=f'{{"headline":"{character}"}}')


@pytest.mark.parametrize("character", SCRIPT_UNSAFE_CHARACTERS)
def test_serialized_json_ld_is_accepted(character: str) -> None:
    # Pins the serializer to the validator: every character the view rejects is a
    # character serialize_json_ld() escapes, so correct output always passes.
    payload = serialize_json_ld({"headline": f"{character} 日本語"})

    assert character not in payload
    assert SocialMetadataView(json_ld=payload).json_ld == payload


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("not-json", "it is not valid JSON"),
        ("post", "it is not valid JSON"),
        ("", "it is not valid JSON"),
        ('["@type"]', "it is not a JSON object"),
        ('"a string"', "it is not a JSON object"),
        # json.dumps() defaults keep a space after ":" and ",", so the value never
        # matches what serialize_json_ld() would have produced.
        (json.dumps({"@type": "Thing"}), "re-serializing it does not reproduce the value"),
        # Last-wins duplicate keys cannot survive a round trip either.
        ('{"a":1,"a":2}', "re-serializing it does not reproduce the value"),
    ],
)
def test_json_ld_rejects_strings_from_other_routes(payload: str, reason: str) -> None:
    # The field's contract is "serialize_json_ld() output only". Rejecting every other
    # route is what keeps a projector mistake from publishing invalid structured data.
    with pytest.raises(ValueError, match=re.escape(reason)):
        SocialMetadataView(json_ld=payload)


def test_template_context_always_contains_empty_metadata() -> None:
    context = empty_context()
    assert isinstance(context, MaatlogTemplateContext)
    assert context.metadata == SocialMetadataView()
    assert as_template_mapping(context)["metadata"] == {
        "open_graph": (),
        "twitter": (),
        "json_ld": None,
    }

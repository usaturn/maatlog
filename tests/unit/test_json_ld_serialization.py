import json

from maatlog.social_metadata import serialize_json_ld


def test_json_ld_serializer_is_script_safe_and_round_trips() -> None:
    value = {
        "headline": '</script><script>alert("x")</script>',
        "description": "apostrophe ' backslash \\\\ newline\n日本語 & < > \u2028 \u2029",
    }
    encoded = serialize_json_ld(value)
    assert "</script" not in encoded.lower()
    assert "<" not in encoded
    assert ">" not in encoded
    assert "&" not in encoded
    assert "\u2028" not in encoded
    assert "\u2029" not in encoded
    assert "\\u2028" in encoded
    assert "\\u2029" in encoded
    assert json.loads(encoded) == value


def test_json_ld_serializer_uses_compact_json() -> None:
    assert serialize_json_ld({"@context": "https://schema.org", "@type": "Thing"}) == (
        '{"@context":"https://schema.org","@type":"Thing"}'
    )

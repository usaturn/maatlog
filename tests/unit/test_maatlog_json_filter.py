"""Unit tests for the maatlog_json Jinja filter."""

from __future__ import annotations

import json

from maatlog.extension import maatlog_json


def test_maatlog_json_encodes_ids_as_compact_ascii_json() -> None:
    encoded = maatlog_json(["sphinx", "data-analysis"])
    assert encoded == '["sphinx","data-analysis"]'
    assert json.loads(encoded) == ["sphinx", "data-analysis"]


def test_maatlog_json_escapes_non_ascii_for_html_attributes() -> None:
    # IDs are ASCII today; ensure_ascii keeps any future / odd values safe in attrs.
    encoded = maatlog_json(["データ 分析"])
    assert "\\u" in encoded
    assert json.loads(encoded) == ["データ 分析"]

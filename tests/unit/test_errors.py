import pytest
from pydantic import BaseModel, ValidationError

from maatlog.errors import (
    Diagnostic,
    MaatlogBuildError,
    format_diagnostic,
    format_location,
    redact_userinfo_in_text,
    safe_value,
)


def test_build_error_sorts_diagnostics_by_source_line_and_code():
    error = MaatlogBuildError(
        [
            Diagnostic(code="z", message="last", source="a", line=2),
            Diagnostic(code="a", message="first", source="a", line=2),
            Diagnostic(code="b", message="middle", source="a", line=1),
        ]
    )

    assert [item.code for item in error.diagnostics] == ["b", "a", "z"]


def test_diagnostic_is_a_frozen_pydantic_model():
    diagnostic = Diagnostic(code="code", message="message")

    assert isinstance(diagnostic, BaseModel)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        field_name = "message"
        setattr(diagnostic, field_name, "changed")


def test_diagnostic_forbids_extra_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Diagnostic.model_validate({"code": "code", "message": "message", "unexpected": True})


def test_format_location_includes_line_when_present() -> None:
    assert format_location("post.rst", 3) == "post.rst:3"
    assert format_location("post.rst", None) == "post.rst"
    assert format_location(None, 3) is None


def test_format_diagnostic_contract_with_all_fields() -> None:
    text = format_diagnostic(
        Diagnostic(
            code="maatlog.metadata.unknown",
            message="Unknown MaatLog metadata key",
            source="post.rst",
            line=3,
            field="maatlog-publshed-at",
            value=repr("x"),
            expected="a documented MaatLog metadata key",
        )
    )

    assert text == (
        "post.rst:3: ERROR: [maatlog.metadata.unknown] Unknown MaatLog metadata key; "
        "field=maatlog-publshed-at; value='x'; expected=a documented MaatLog metadata key"
    )


def test_format_diagnostic_omits_absent_optional_parts() -> None:
    text = format_diagnostic(Diagnostic(code="maatlog.x", message="only message"))

    assert text == "ERROR: [maatlog.x] only message"
    assert "field=" not in text
    assert "value=" not in text
    assert "expected=" not in text


def test_safe_value_redacts_userinfo_and_truncates() -> None:
    long_secret = "https://user:hunter2@example.com/" + ("a" * 200)
    diagnostic = Diagnostic(code="c", message="m", value=repr(long_secret))

    rendered = safe_value(diagnostic)
    assert rendered is not None
    assert "user" not in rendered
    assert "hunter2" not in rendered
    assert "example.com" in rendered
    assert rendered.endswith("...")
    assert len(rendered) <= 120


def test_redact_userinfo_in_text_preserves_urls_without_credentials() -> None:
    assert redact_userinfo_in_text("https://example.com/path") == "https://example.com/path"
    assert redact_userinfo_in_text("https://u:p@example.com:99999/") == "https://example.com:99999/"


def test_build_error_message_uses_format_diagnostic() -> None:
    error = MaatlogBuildError(
        [
            Diagnostic(
                code="maatlog.slug.invalid",
                message="Invalid post slug",
                source="a.rst",
                line=2,
                field="maatlog-slug",
                value=repr("BAD"),
                expected="[a-z0-9][a-z0-9._-]*",
            )
        ]
    )

    assert "ERROR: [maatlog.slug.invalid]" in str(error)
    assert "field=maatlog-slug" in str(error)
    assert "; " in str(error)

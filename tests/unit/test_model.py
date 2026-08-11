from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError

from maatlog.errors import MaatlogBuildError
from maatlog.model import Post, PublicationStatus, parse_datetime, parse_optional_datetime, publication_status


@pytest.mark.parametrize(
    ("published", "expires", "expected"),
    [
        (None, None, PublicationStatus.DRAFT),
        ("2026-08-02T00:00:00Z", None, PublicationStatus.SCHEDULED),
        ("2026-08-01T00:00:00Z", None, PublicationStatus.PUBLISHED),
        ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", PublicationStatus.EXPIRED),
    ],
)
def test_publication_status(
    published: str | None,
    expires: str | None,
    expected: PublicationStatus,
) -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    published_at = parse_optional_datetime(published, ZoneInfo("UTC"))
    expires_at = parse_optional_datetime(expires, ZoneInfo("UTC"))

    assert publication_status(published_at, expires_at, now) is expected


def test_optional_datetime_keeps_none() -> None:
    assert parse_optional_datetime(None, ZoneInfo("UTC")) is None


def test_parse_datetime_exposes_the_datetime_parser_contract() -> None:
    assert parse_datetime("2026-08-01T00:00:00Z", ZoneInfo("UTC")) == datetime(2026, 8, 1, tzinfo=UTC)


def test_optional_datetime_keeps_explicit_offset() -> None:
    parsed = parse_optional_datetime("2026-08-01T09:30:00+09:00", ZoneInfo("UTC"))

    assert parsed == datetime(2026, 8, 1, 9, 30, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_optional_datetime_assigns_configured_timezone_to_naive_input() -> None:
    timezone = ZoneInfo("Europe/Berlin")

    parsed = parse_optional_datetime("2026-08-01T09:30:00", timezone)

    assert parsed is not None
    assert parsed == datetime(2026, 8, 1, 9, 30, tzinfo=timezone)
    assert parsed.tzinfo is timezone
    assert parsed.fold == 0


@pytest.mark.parametrize("value", ["2026-10-25T02:30:00", "2026-03-29T02:30:00"])
def test_optional_datetime_rejects_ambiguous_and_nonexistent_local_times(value: str) -> None:
    with pytest.raises(MaatlogBuildError) as error:
        parse_optional_datetime(value, ZoneInfo("Europe/Berlin"))

    assert error.value.diagnostics[0].code == "maatlog.datetime.invalid"


def test_publication_status_rejects_expiry_without_publication() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        publication_status(None, datetime(2026, 8, 2, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC))

    assert error.value.diagnostics[0].code == "maatlog.datetime.invalid"


def test_publication_status_rejects_expiry_at_or_before_publication() -> None:
    published_at = datetime(2026, 8, 1, tzinfo=UTC)

    with pytest.raises(MaatlogBuildError) as error:
        publication_status(published_at, published_at, published_at)

    assert error.value.diagnostics[0].code == "maatlog.datetime.invalid"


def test_post_is_a_frozen_pydantic_authoring_record() -> None:
    published_at = datetime(2026, 8, 1, tzinfo=UTC)
    post = Post(
        docname="blog/hello",
        source_path="blog/hello.md",
        title="Hello",
        slug="hello",
        published_at=published_at,
        expires_at=None,
        tags=("release",),
        categories=("news",),
        authors=("maat",),
        excerpt=None,
        image_uri=None,
        canonical_url=None,
        external_url=None,
        status=PublicationStatus.PUBLISHED,
    )

    assert isinstance(post, BaseModel)
    assert post.status is PublicationStatus.PUBLISHED
    with pytest.raises(ValidationError, match="Instance is frozen"):
        field_name = "title"
        setattr(post, field_name, "Changed")


def test_post_forbids_extra_fields() -> None:
    values = _post_values()
    values["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Post.model_validate(values)


@pytest.mark.parametrize("field_name", ["published_at", "expires_at"])
def test_post_rejects_naive_stored_datetimes(field_name: str) -> None:
    values = _post_values()
    values[field_name] = datetime(2026, 8, 2)

    with pytest.raises(ValidationError) as error:
        Post.model_validate(values)

    assert error.value.errors()[0]["type"] == "timezone_aware"


def _post_values() -> dict[str, object]:
    return {
        "docname": "blog/hello",
        "source_path": "blog/hello.md",
        "title": "Hello",
        "slug": "hello",
        "published_at": datetime(2026, 8, 1, tzinfo=UTC),
        "expires_at": datetime(2026, 8, 2, tzinfo=UTC),
        "tags": ("release",),
        "categories": ("news",),
        "authors": ("maat",),
        "excerpt": None,
        "image_uri": None,
        "canonical_url": None,
        "external_url": None,
        "status": PublicationStatus.PUBLISHED,
    }

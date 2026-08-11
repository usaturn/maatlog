from datetime import UTC, datetime
from enum import StrEnum
from typing import Never
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .errors import Diagnostic, MaatlogBuildError


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    EXPIRED = "expired"


class Post(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    docname: str
    source_path: str
    title: str
    slug: str
    published_at: AwareDatetime | None
    expires_at: AwareDatetime | None
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    authors: tuple[str, ...]
    excerpt: str | None
    image_uri: str | None
    canonical_url: str | None
    external_url: str | None
    status: PublicationStatus


def parse_optional_datetime(value: str | None, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    return parse_datetime(value, timezone)


def parse_datetime(value: str, timezone: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except TypeError, ValueError:
        _invalid_datetime("datetime", value, "an ISO 8601 datetime")

    if parsed.tzinfo is not None:
        return parsed
    return _resolve_local_datetime(parsed, timezone, value)


def publication_status(
    published_at: datetime | None, expires_at: datetime | None, build_time: datetime
) -> PublicationStatus:
    if expires_at is not None and published_at is None:
        _invalid_datetime("expires", expires_at.isoformat(), "an expiry with a publication time")
    if expires_at is not None and published_at is not None and expires_at <= published_at:
        _invalid_datetime("expires", expires_at.isoformat(), "a time after publication")
    if published_at is None:
        return PublicationStatus.DRAFT
    if published_at > build_time:
        return PublicationStatus.SCHEDULED
    if expires_at is not None and build_time >= expires_at:
        return PublicationStatus.EXPIRED
    return PublicationStatus.PUBLISHED


def _resolve_local_datetime(local: datetime, timezone: ZoneInfo, value: str) -> datetime:
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = local.replace(tzinfo=timezone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(timezone)
        if round_trip.replace(tzinfo=None) == local:
            candidates.setdefault(candidate.astimezone(UTC), candidate)

    if len(candidates) != 1:
        _invalid_datetime("datetime", value, "an unambiguous local ISO 8601 datetime")
    return next(iter(candidates.values()))


def _invalid_datetime(field: str, value: str, expected: str) -> Never:
    raise MaatlogBuildError(
        [
            Diagnostic(
                code="maatlog.datetime.invalid",
                message="Invalid datetime",
                field=field,
                value=repr(value),
                expected=expected,
            )
        ]
    )

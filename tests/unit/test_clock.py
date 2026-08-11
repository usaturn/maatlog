from datetime import UTC, datetime

import pytest

from maatlog.clock import resolve_build_time
from maatlog.errors import MaatlogBuildError


def test_source_date_epoch_is_preferred_without_reading_system_clock() -> None:
    def clock() -> datetime:
        raise AssertionError("system clock must not be read when SOURCE_DATE_EPOCH is set")

    build_time = resolve_build_time({"SOURCE_DATE_EPOCH": "1785542400"}, clock)

    assert build_time == datetime(2026, 8, 1, tzinfo=UTC)


def test_system_clock_is_read_once_when_source_date_epoch_is_absent() -> None:
    calls = 0
    expected = datetime(2026, 8, 1, tzinfo=UTC)

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return expected

    assert resolve_build_time({}, clock) is expected
    assert calls == 1


def test_invalid_source_date_epoch_uses_dedicated_diagnostic_code() -> None:
    with pytest.raises(MaatlogBuildError) as error:
        resolve_build_time({"SOURCE_DATE_EPOCH": "not-an-epoch"}, lambda: datetime(2026, 8, 1, tzinfo=UTC))

    assert error.value.diagnostics[0].code == "maatlog.source-date-epoch.invalid"

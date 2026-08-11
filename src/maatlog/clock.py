from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from .errors import Diagnostic, MaatlogBuildError


def resolve_build_time(environ: Mapping[str, str], clock: Callable[[], datetime]) -> datetime:
    source_date_epoch = environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is None:
        return clock()

    try:
        return datetime.fromtimestamp(int(source_date_epoch), UTC)
    except OverflowError, OSError, ValueError:
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code="maatlog.source-date-epoch.invalid",
                    message="Invalid SOURCE_DATE_EPOCH",
                    field="SOURCE_DATE_EPOCH",
                    value=repr(source_date_epoch),
                    expected="Unix seconds",
                )
            ]
        ) from None

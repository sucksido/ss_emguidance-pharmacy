"""The single boundary between UTC storage and Africa/Johannesburg business logic.

Rules of the road (see DECISIONS.md, ADR-006):

* Every timestamp that crosses the API or the database is timezone-aware and is
  stored as ``timestamptz`` (i.e. UTC).
* Every *business* concept - "which rule is in force on this day", "the 30 days
  ending at this dispense" - is expressed as a local calendar ``date`` in
  ``BUSINESS_TZ``.
* Conversion between the two happens only through the functions in this module.
  Nothing else in the code base calls ``astimezone`` or builds midnight
  boundaries by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Africa/Johannesburg")
BUSINESS_TZ_NAME = "Africa/Johannesburg"

#: Length of the rolling quantity window, in local calendar days, including the
#: day of the dispense itself.
ROLLING_WINDOW_DAYS = 30


def ensure_aware(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("timestamp must be timezone-aware")
    return ts


def to_utc(ts: datetime) -> datetime:
    return ensure_aware(ts).astimezone(UTC)


def business_date(ts: datetime) -> date:
    """The Africa/Johannesburg calendar date on which an instant falls."""
    return ensure_aware(ts).astimezone(BUSINESS_TZ).date()


def start_of_business_day_utc(d: date) -> datetime:
    """The UTC instant at which local day ``d`` begins (00:00 SAST)."""
    return datetime.combine(d, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)


def rolling_window(anchor: date) -> tuple[date, date]:
    """Inclusive local-date bounds of the 30-day window ending on ``anchor``."""
    return anchor - timedelta(days=ROLLING_WINDOW_DAYS - 1), anchor


def utc_bounds(first_day: date, last_day: date) -> tuple[datetime, datetime]:
    """Half-open UTC interval ``[start, end)`` covering local days first..last inclusive.

    Queries use these bounds directly against ``dispensed_at`` so that the
    b-tree index on the raw ``timestamptz`` column stays usable.
    """
    return start_of_business_day_utc(first_day), start_of_business_day_utc(last_day + timedelta(days=1))


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Test clock. Kept here rather than in tests so services can type against it."""

    def __init__(self, at: datetime) -> None:
        self._at = to_utc(at)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = to_utc(at)

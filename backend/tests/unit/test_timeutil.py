from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.timeutil import business_date, rolling_window, start_of_business_day_utc, utc_bounds


def test_business_date_uses_johannesburg_not_utc():
    assert business_date(datetime(2026, 3, 31, 21, 59, tzinfo=UTC)) == date(2026, 3, 31)
    assert business_date(datetime(2026, 3, 31, 22, 0, tzinfo=UTC)) == date(2026, 4, 1)


def test_business_date_ignores_the_callers_offset():
    # Same instant expressed in three offsets lands on the same business day.
    instant = datetime(2026, 3, 31, 22, 30, tzinfo=UTC)
    for tz in (UTC, timezone(timedelta(hours=-5)), timezone(timedelta(hours=9))):
        assert business_date(instant.astimezone(tz)) == date(2026, 4, 1)


def test_naive_timestamps_are_refused():
    with pytest.raises(ValueError):
        business_date(datetime(2026, 1, 1, 12, 0))


def test_start_of_business_day_is_22_00_utc_previous_day():
    assert start_of_business_day_utc(date(2026, 4, 1)) == datetime(2026, 3, 31, 22, 0, tzinfo=UTC)


def test_rolling_window_has_30_days_inclusive():
    start, end = rolling_window(date(2026, 6, 15))
    assert (end - start).days + 1 == 30
    assert start == date(2026, 5, 17)


def test_utc_bounds_are_half_open_local_days():
    lo, hi = utc_bounds(date(2026, 6, 1), date(2026, 6, 1))
    assert lo == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert hi == datetime(2026, 6, 1, 22, 0, tzinfo=UTC)

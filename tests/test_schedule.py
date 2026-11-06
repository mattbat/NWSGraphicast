from __future__ import annotations

from datetime import UTC, datetime

import pytest

from graphicast.schedule import current_slot, should_run


def utc(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def test_cdt_first_run() -> None:
    now = utc(2026, 7, 15, 11, 5)
    run, slot, _ = should_run(now, None)
    assert run
    assert slot is not None and slot.isoformat() == "2026-07-15T06:00:00-05:00"


def test_cdt_already_done() -> None:
    run, slot, reason = should_run(utc(2026, 7, 15, 12, 5), "2026-07-15T06:00:00-05:00")
    assert not run
    assert slot is not None and slot.hour == 6
    assert "already" in reason


def test_cdt_delayed_run_catches_up() -> None:
    run, slot, _ = should_run(utc(2026, 7, 15, 12, 5), None)
    assert run and slot is not None and slot.hour == 6


def test_cst_run() -> None:
    run, slot, _ = should_run(utc(2026, 1, 15, 12, 5), None)
    assert run
    assert slot is not None and slot.isoformat() == "2026-01-15T06:00:00-06:00"


def test_cst_before_window() -> None:
    run, slot, reason = should_run(utc(2026, 1, 15, 11, 5), None)
    assert not run and slot is None
    assert reason


def test_previous_day_evening_slot() -> None:
    slot = current_slot(utc(2026, 1, 16, 0, 10))
    assert slot is not None and slot.isoformat() == "2026-01-15T18:00:00-06:00"


def test_window_boundary_exclusive() -> None:
    assert current_slot(utc(2026, 1, 15, 14, 59)) is not None
    assert current_slot(utc(2026, 1, 15, 15, 0)) is None


def test_exact_slot_time_included() -> None:
    assert current_slot(utc(2026, 1, 15, 12, 0)) is not None


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 3, 8, 12, 0), "2026-03-08T06:00:00-05:00"),  # CDT after spring forward
        (utc(2026, 3, 8, 13, 0), "2026-03-08T06:00:00-05:00"),
        (utc(2026, 11, 1, 12, 0), "2026-11-01T06:00:00-06:00"),  # CST after fall back
        (utc(2026, 11, 1, 13, 0), "2026-11-01T06:00:00-06:00"),
    ],
)
def test_dst_days(now: datetime, expected: str) -> None:
    slot = current_slot(now)
    assert slot is not None and slot.isoformat() == expected


def test_dst_spring_utc_noon_is_cdt_morning() -> None:
    # 12:00 UTC on 2026-03-08 is 07:00 CDT; slot 06:00 CDT is 1h ago.
    slot = current_slot(utc(2026, 3, 8, 12, 0))
    assert slot is not None and slot.utcoffset().total_seconds() == -5 * 3600


def test_custom_tz_and_hours() -> None:
    slot = current_slot(utc(2026, 7, 15, 9, 30), tz="UTC", hours=(9,))
    assert slot is not None and slot.hour == 9


def test_input_in_other_zone() -> None:
    from zoneinfo import ZoneInfo

    now = datetime(2026, 7, 15, 13, 5, tzinfo=ZoneInfo("America/New_York"))
    run, slot, _ = should_run(now, None)
    assert run and slot is not None and slot.hour == 12

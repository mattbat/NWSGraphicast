"""Send-slot schedule gate (6/12/18 local time by default)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Chicago"
DEFAULT_HOURS = (6, 12, 18)
WINDOW = timedelta(hours=3)


def current_slot(
    now: datetime, tz: str = DEFAULT_TZ, hours: Sequence[int] = DEFAULT_HOURS
) -> datetime | None:
    """Latest local slot at or before `now`, if within WINDOW; else None."""
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    best: datetime | None = None
    for day in (local.date() - timedelta(days=1), local.date()):
        for hour in hours:
            slot = datetime.combine(day, time(hour), tzinfo=zone)
            if slot <= local and (best is None or slot > best):
                best = slot
    if best is None or local - best >= WINDOW:
        return None
    return best


def should_run(
    now: datetime,
    last_slot_iso: str | None,
    tz: str = DEFAULT_TZ,
    hours: Sequence[int] = DEFAULT_HOURS,
) -> tuple[bool, datetime | None, str]:
    slot = current_slot(now, tz, hours)
    if slot is None:
        return False, None, "not within a send slot window"
    if slot.isoformat() == last_slot_iso:
        return False, slot, f"slot {slot.isoformat()} already processed"
    return True, slot, f"slot {slot.isoformat()} not yet processed"

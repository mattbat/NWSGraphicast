"""Graphic data model shared by all sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Graphic:
    number: int
    order: int
    title: str
    description: str | None
    image_url: str
    start: datetime
    end: datetime

    def is_active(self, now: datetime) -> bool:
        return self.start <= now < self.end


def active_graphics(graphics: list[Graphic], now: datetime) -> list[Graphic]:
    """Active graphics sorted by (order, number)."""
    return sorted((g for g in graphics if g.is_active(now)), key=lambda g: (g.order, g.number))


def _required(fields: Mapping[str, str], key: str) -> str:
    value = fields.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"missing required field: {key}")
    return str(value).strip()


def _int(fields: Mapping[str, str], key: str) -> int:
    raw = _required(fields, key)
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"invalid integer for {key}: {raw!r}") from None


def _epoch(fields: Mapping[str, str], key: str) -> datetime:
    seconds = _int(fields, key)
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        raise ValueError(f"invalid timestamp for {key}: {seconds!r}") from None


def _text(fields: Mapping[str, str], key: str) -> str:
    value = fields.get(key)
    return "" if value is None else str(value).strip()


def graphic_from_fields(fields: Mapping[str, str]) -> Graphic:
    """Build a Graphic from raw feed keys. Raises ValueError naming the bad key."""
    number = _int(fields, "graphicNumber")
    start = _epoch(fields, "StartTime")
    end = _epoch(fields, "EndTime")
    full_image = _required(fields, "FullImage")
    order = _int(fields, "order") if _text(fields, "order") else number
    loop = _text(fields, "ImageLoop")
    image_url = loop if _text(fields, "radar") == "1" and loop else full_image
    description: str | None = _text(fields, "description")
    if not description or description.lower() == "none":
        description = None
    return Graphic(
        number=number,
        order=order,
        title=_text(fields, "title"),
        description=description,
        image_url=image_url,
        start=start,
        end=end,
    )

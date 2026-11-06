"""Severe-weather assessment: SPC convective outlooks, active alerts and keyword mentions.

`assess` never raises. Each failed source is logged and sets `ok=False`, so the caller can
tell "no risk" from "couldn't check". See docs/IMPLEMENTATION.md section 12.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from graphicast.model import Graphic

log = logging.getLogger(__name__)

SPC_URL = "https://www.spc.noaa.gov/products/outlook/day{day}otlk_cat.lyr.geojson"
ALERTS_URL = "https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
LEVELS = {
    "MRGL": (1, "Marginal"),
    "SLGT": (2, "Slight"),
    "ENH": (3, "Enhanced"),
    "MDT": (4, "Moderate"),
    "HIGH": (5, "High"),
}  # TSTM and anything else is ignored
FLAG_LEVEL = 2
OUTLOOK_DAYS = (1, 2, 3)

ALERT_KEYWORDS = (
    "Tornado",
    "Severe Thunderstorm",
    "Flash Flood",
    "Blizzard",
    "Winter Storm",
    "Ice Storm",
    "Extreme Cold",
    "Extreme Heat",
    "Excessive Heat",
    "High Wind",
    "Hurricane",
    "Tropical Storm",
    "Dust Storm",
)

_NEGATION = re.compile(r"\b(no|not|unlikely|without|none)\b|n't\b", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")
_MENTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), label)
    for pattern, label in (
        (r"\btornado(es)?\b", "tornadoes"),
        (r"\b(large|very large|giant) hail\b", "large hail"),
        (r"\b(damaging|destructive) winds?\b", "damaging winds"),
        (r"\bsevere (storms?|thunderstorms?|weather)\b", "severe storms"),
        (r"\bblizzard\b", "blizzard"),
        (r"\bice storm\b|\bfreezing rain\b|\bicing\b", "ice"),
        (r"\bheavy snow\b|\bwinter storm\b", "heavy snow"),
        (r"\bflash flood(ing)?\b", "flash flooding"),
    )
)


@dataclass(frozen=True)
class Outlook:
    day: int
    level: int
    name: str
    valid: datetime  # VALID_ISO, UTC


@dataclass(frozen=True)
class Alert:
    event: str
    headline: str


@dataclass(frozen=True)
class Severity:
    outlooks: tuple[Outlook, ...] = ()  # only days with level >= 1, sorted by day
    alerts: tuple[Alert, ...] = ()
    mentions: tuple[str, ...] = ()  # canonical keyword labels, de-duplicated, in order found
    ok: bool = True  # False if any official source failed

    @property
    def max_level(self) -> int:
        return max((o.level for o in self.outlooks), default=0)

    @property
    def flagged(self) -> bool:
        return self.max_level >= FLAG_LEVEL or bool(self.alerts)


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Even-odd ray casting against one ring of [lon, lat] points."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """First ring is the outer boundary; later rings are holes."""
    if not rings or not _in_ring(lon, lat, rings[0]):
        return False
    return not any(_in_ring(lon, lat, hole) for hole in rings[1:])


def point_in_geometry(lon: float, lat: float, geometry: Mapping) -> bool:
    """True if the point is inside a GeoJSON Polygon or MultiPolygon (other types: False)."""
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        return _in_polygon(lon, lat, coords)
    if kind == "MultiPolygon":
        return any(_in_polygon(lon, lat, polygon) for polygon in coords)
    return False


def parse_spc(text: str, day: int, lat: float, lon: float) -> Outlook | None:
    """The highest categorical level whose area contains the point, or None."""
    best: Outlook | None = None
    for feature in json.loads(text).get("features", []):
        props = feature.get("properties") or {}
        level_name = LEVELS.get(props.get("LABEL"))
        if level_name is None or (best is not None and level_name[0] <= best.level):
            continue
        if point_in_geometry(lon, lat, feature.get("geometry") or {}):
            valid = datetime.fromisoformat(props["VALID_ISO"])
            best = Outlook(day, level_name[0], level_name[1], valid)
    return best


def parse_alerts(text: str) -> tuple[Alert, ...]:
    """Severe/winter/flood/heat watches and warnings, de-duplicated by event name."""
    found: dict[str, Alert] = {}
    for feature in json.loads(text).get("features", []):
        props = feature.get("properties") or {}
        event = props.get("event") or ""
        if not event.endswith(("Watch", "Warning")):
            continue
        if not any(k in event for k in ALERT_KEYWORDS):
            continue
        found.setdefault(event, Alert(event, props.get("headline") or ""))
    return tuple(found.values())


def find_mentions(graphics: Iterable[Graphic]) -> tuple[str, ...]:
    """Keyword labels found in graphic titles and descriptions.

    Text is split into sentences; any sentence containing a negation word is skipped, so
    "Tornadoes are not expected." yields nothing (and so does "Severe storms possible;
    tornadoes unlikely.", where the negation shares the sentence). Labels are de-duplicated
    and kept in the order they appear.
    """
    labels: list[str] = []
    for g in graphics:
        for text in (g.title, g.description or ""):
            for sentence in _SENTENCE_SPLIT.split(text):
                if _NEGATION.search(sentence):
                    continue
                hits = sorted(
                    (m.start(), label)
                    for pattern, label in _MENTION_PATTERNS
                    if (m := pattern.search(sentence))
                )
                labels.extend(label for _, label in hits if label not in labels)
    return tuple(labels)


def assess_official(lat: float, lon: float, get: Callable[..., bytes]) -> Severity:
    """Fetch only the official sources (SPC days 1-3 and active alerts) for the point, with no
    keyword mentions. Never raises; failures log a warning and set ok=False while the other
    sources are still used."""
    ok = True
    outlooks: list[Outlook] = []
    for day in OUTLOOK_DAYS:
        url = SPC_URL.format(day=day)
        try:
            outlook = parse_spc(get(url).decode("utf-8"), day, lat, lon)
        except Exception as exc:
            log.warning("SPC day %d outlook failed: %s", day, exc)
            ok = False
            continue
        if outlook is not None:
            outlooks.append(outlook)
    alerts: tuple[Alert, ...] = ()
    try:
        alerts = parse_alerts(get(ALERTS_URL.format(lat=lat, lon=lon)).decode("utf-8"))
    except Exception as exc:
        log.warning("active alerts fetch failed: %s", exc)
        ok = False
    return Severity(tuple(outlooks), alerts, (), ok)


def with_mentions(sev: Severity, graphics: Iterable[Graphic]) -> Severity:
    """`sev` with keyword mentions computed from the graphics."""
    return replace(sev, mentions=find_mentions(graphics))


def assess(
    graphics: Iterable[Graphic], lat: float, lon: float, get: Callable[..., bytes]
) -> Severity:
    """Official sources plus keyword mentions from the graphics. Never raises."""
    return with_mentions(assess_official(lat, lon, get), graphics)


def snapshot(sev: Severity) -> dict:
    """The part of a Severity saved in state, to detect a later rise."""
    return {"max_level": sev.max_level, "alerts": sorted(a.event for a in sev.alerts)}


def severity_rose(sev: Severity, saved: object) -> bool:
    """True if the risk went up versus the saved baseline. No baseline, or a failed
    assessment, is never a rise; Marginal alone never triggers."""
    if not sev.ok or not isinstance(saved, dict):
        return False
    level = saved.get("max_level")
    alerts = saved.get("alerts")
    if not isinstance(level, int) or not isinstance(alerts, list):
        return False
    if sev.max_level >= FLAG_LEVEL and sev.max_level > level:
        return True
    return any(a.event not in alerts for a in sev.alerts)

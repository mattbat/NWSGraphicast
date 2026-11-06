"""Current conditions for the email's weather widget (api.weather.gov), docs section 14.

`fetch_conditions` never raises: any failure is logged and returns None, which simply means
"no widget". Sunrise and sunset use the NOAA solar-position algorithm (stdlib `math`)."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

POINTS_URL = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
OBSERVATION_STATIONS = 4  # how many nearest stations to try
OBSERVATION_MAX_AGE = timedelta(hours=2)
HOURS_SHOWN = 6
POP_WINDOW = 12  # hours scanned for the headline chance of rain

# Substring -> Lucide icon, first match wins (docs/widget_mockup.py `lucide`). Differences:
# "partly cloudy" maps to the part-cloud icons (the mockup's bare "cloudy" rule hid them), and
# "fair" / "few clouds" are added because observation text uses them for mostly clear skies.
_ICON_RULES: tuple[tuple[str, str], ...] = (
    ("thunder", "cloud-lightning"),
    ("snow", "cloud-snow"),
    ("sleet", "cloud-snow"),
    ("flurr", "cloud-snow"),
    ("freezing", "cloud-hail"),
    ("ice", "cloud-hail"),
    ("drizzle", "cloud-drizzle"),
    ("rain", "cloud-rain"),
    ("shower", "cloud-rain"),
    ("fog", "cloud-fog"),
    ("haze", "cloud-fog"),
    ("smoke", "cloud-fog"),
    ("mist", "cloud-fog"),
    ("mostly cloudy", "cloudy"),
    ("overcast", "cloudy"),
)


def icon_for(text: str, day: bool = True) -> str:
    """Icon name for a forecast/observation phrase; only the part before " then " counts."""
    s = text.lower().split(" then ")[0]
    for key, icon in _ICON_RULES:
        if key in s:
            return icon
    for key in ("partly", "few clouds"):
        if key in s:
            return "cloud-sun" if day else "cloud-moon"
    if "cloudy" in s:
        return "cloudy"
    if "mostly sunny" in s:
        return "cloud-sun"
    if "mostly clear" in s:
        return "cloud-moon"
    if "sunny" in s:
        return "sun"
    if "clear" in s or "fair" in s:
        return "sun" if day else "moon"
    if "wind" in s:
        return "wind"
    return "thermometer"


# Every icon name the widget can use (mapping results plus the fixed ones).
ICON_NAMES = frozenset(
    {icon for _, icon in _ICON_RULES}
    | {"cloud-sun", "cloud-moon", "sun", "moon", "wind", "thermometer"}
    | {"sunrise", "sunset", "droplet", "navigation"}
)


@dataclass(frozen=True)
class Hour:
    label: str  # "Now", "9AM", ...
    icon: str
    temp: int
    pop: int


@dataclass(frozen=True)
class Conditions:
    place: str
    temp: int
    text: str
    icon: str
    feels: int | None
    hi_lo: str  # "H:55°  L:40°" or "L:40° · Sat H:59°"
    hours: tuple[Hour, ...]
    sunrise: datetime  # local tz
    sunset: datetime
    wind: str  # "NNE 8", "S 10–15", "Calm"
    pop: int  # max hourly precip % over the next 12 h
    is_day: bool
    outlook: str = ""  # "Tonight: Partly Cloudy, low 40°"; "" when unavailable


def sun_times(day: date, lat: float, lon: float, tz: str) -> tuple[datetime, datetime]:
    """(sunrise, sunset) on a local date, as local-tz datetimes (NOAA general solar position
    calculations, accurate to about a minute; polar day/night is clamped)."""
    zone = ZoneInfo(tz)
    # The Sun's position barely moves in a day, so evaluate it once at local noon.
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=zone)
    g = 2 * math.pi / 365 * (noon.timetuple().tm_yday - 1 + (noon.hour - 12) / 24)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    phi = math.radians(lat)
    cos_ha = math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(decl)) - math.tan(
        phi
    ) * math.tan(decl)
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_ha))))
    base = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("UTC"))
    out = []
    for sign in (1, -1):  # sunrise, then sunset
        minutes = 720 - 4 * (lon + sign * ha) - eqtime
        local = (base + timedelta(minutes=minutes)).astimezone(zone)
        # Far from the prime meridian the UTC date can differ from the local one.
        local += timedelta(days=(day - local.date()).days)
        out.append(local)
    return out[0], out[1]


def _f(celsius: float) -> int:
    return round(celsius * 9 / 5 + 32)


def _wind(period: dict) -> str:
    """ "8 mph" -> "NNE 8"; "5 to 10 mph" -> "NNE 5–10"; "0 mph" -> "Calm"."""
    nums = re.findall(r"\d+", str(period.get("windSpeed", "")))
    if not nums or all(int(n) == 0 for n in nums):
        return "Calm"
    speed = "–".join(dict.fromkeys(nums[:2])) if len(nums) > 1 else nums[0]
    return f"{period.get('windDirection', '')} {speed}".strip()


def _hi_lo(periods: list[dict], tz: str) -> str:
    p0, p1 = periods[0], periods[1]
    if p0["isDaytime"]:
        return f"H:{p0['temperature']}°  L:{p1['temperature']}°"
    day = datetime.fromisoformat(p1["startTime"]).astimezone(ZoneInfo(tz))
    return f"L:{p0['temperature']}° · {day:%a} H:{p1['temperature']}°"


def _outlook(periods: list[dict]) -> str:
    """One line for the forecast period after the first (the one hi/lo is based on); "" if the
    data is missing or malformed."""
    try:
        p = periods[1]
        name, short = str(p["name"]).strip(), str(p["shortForecast"]).strip().rstrip(".")
        temp = int(p["temperature"])
        kind = "high" if p["isDaytime"] else "low"
        return f"{name}: {short}, {kind} {temp}°" if name and short else ""
    except Exception as exc:
        log.debug("outlook unavailable: %s", exc)
        return ""


def _json(get: Callable[..., bytes], url: str) -> dict:
    return json.loads(get(url).decode("utf-8"))


def _observation(
    stations: list[str], now: datetime, get: Callable[..., bytes]
) -> tuple[int, str, int | None] | None:
    """(temp °F, text, feels °F) from the first recent station reporting a temperature."""
    for station in stations[:OBSERVATION_STATIONS]:
        try:
            props = _json(get, f"{station}/observations/latest")["properties"]
            temp_c = props["temperature"]["value"]
            stamp = datetime.fromisoformat(props["timestamp"])
        except Exception as exc:
            log.debug("observation from %s unusable: %s", station, exc)
            continue
        if temp_c is None or now - stamp > OBSERVATION_MAX_AGE:
            continue
        feels_c = next(
            (
                props[k]["value"]
                for k in ("windChill", "heatIndex")
                if (props.get(k) or {}).get("value") is not None
            ),
            None,
        )
        return (
            _f(temp_c),
            (props.get("textDescription") or "").strip(),
            (None if feels_c is None else _f(feels_c)),
        )
    return None


def _start(periods: list[dict], now: datetime) -> int:
    """Index of the hourly period containing `now`, or else the first one after it."""
    for i, p in enumerate(periods):
        if datetime.fromisoformat(p["endTime"]) > now:
            return i
    raise ValueError("no hourly period at or after now")


def _pop(period: dict) -> int:
    return (period.get("probabilityOfPrecipitation") or {}).get("value") or 0


def _hours(periods: list[dict], tz: str, temp: int, icon: str) -> list[Hour]:
    """Hour entries for `periods`. The first is "Now" and uses the observed temperature and
    icon, so it matches the current conditions shown above it."""
    zone = ZoneInfo(tz)
    hours = []
    for i, p in enumerate(periods):
        t = datetime.fromisoformat(p["startTime"]).astimezone(zone)
        label = "Now" if i == 0 else f"{int(t.strftime('%I'))}{t:%p}"
        hours.append(
            Hour(
                label,
                icon if i == 0 else icon_for(p["shortForecast"], p["isDaytime"]),
                temp if i == 0 else p["temperature"],
                _pop(p),
            )
        )
    return hours


def fetch_conditions(
    lat: float,
    lon: float,
    place: str,
    tz: str,
    now: datetime,
    get: Callable[..., bytes],
) -> Conditions | None:
    """Current conditions, today's high/low, six hours, wind and sun times; None on failure."""
    try:
        return _fetch(lat, lon, place, tz, now, get)
    except Exception as exc:
        log.warning("weather widget unavailable: %s", exc)
        return None


def _fetch(
    lat: float, lon: float, place: str, tz: str, now: datetime, get: Callable[..., bytes]
) -> Conditions:
    points = _json(get, POINTS_URL.format(lat=lat, lon=lon))["properties"]
    forecast = _json(get, points["forecast"])["properties"]["periods"]
    hourly = _json(get, points["forecastHourly"])["properties"]["periods"]
    try:
        stations = [f["id"] for f in _json(get, points["observationStations"])["features"]]
    except Exception as exc:
        log.debug("station list unavailable: %s", exc)
        stations = []
    observed = _observation(stations, now, get)

    start = _start(hourly, now)
    current = hourly[start]
    if observed:
        temp, text, feels = observed
        text = text or current["shortForecast"]
    else:
        temp, text, feels = current["temperature"], current["shortForecast"], None
    if feels == temp:
        feels = None

    rise, sset = sun_times(now.astimezone(ZoneInfo(tz)).date(), lat, lon, tz)
    is_day = rise <= now < sset
    icon = icon_for(text, is_day)
    return Conditions(
        place=place,
        temp=temp,
        text=text,
        icon=icon,
        feels=feels,
        hi_lo=_hi_lo(forecast, tz),
        hours=tuple(_hours(hourly[start : start + HOURS_SHOWN], tz, temp, icon)),
        sunrise=rise,
        sunset=sset,
        wind=_wind(forecast[0]),
        pop=max(_pop(p) for p in hourly[start : start + POP_WINDOW]),
        is_day=is_day,
        outlook=_outlook(forecast),
    )

from __future__ import annotations

import copy
import json
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from graphicast.weather import (
    ICON_NAMES,
    POINTS_URL,
    fetch_conditions,
    icon_for,
    sun_times,
)

FIX = Path(__file__).parent / "fixtures" / "weather"
LAT, LON, TZ = 35.6528, -97.4781, "America/Chicago"
NOW = datetime(2026, 11, 6, 14, 40, tzinfo=UTC)
BASE = "https://api.weather.gov/gridpoints/OUN/99,102"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def served(**over) -> dict:
    """URL -> bytes for the real fixtures; `over` replaces a value (bytes or Exception)."""
    m = {
        POINTS_URL.format(lat=LAT, lon=LON): (FIX / "points.json").read_bytes(),
        f"{BASE}/forecast": (FIX / "forecast.json").read_bytes(),
        f"{BASE}/forecast/hourly": (FIX / "hourly.json").read_bytes(),
        f"{BASE}/stations": (FIX / "stations.json").read_bytes(),
        "https://api.weather.gov/stations/KPWA/observations/latest": (
            FIX / "observation_KPWA.json"
        ).read_bytes(),
    }
    m.update(over)
    return m


def fetch(fake_get, mapping=None, now=NOW):
    return fetch_conditions(LAT, LON, "Edmond", TZ, now, fake_get(mapping or served()))


def jb(obj) -> bytes:
    return json.dumps(obj).encode()


def test_fetch_on_fixtures(fake_get):
    c = fetch(fake_get)
    assert c is not None
    assert (c.place, c.temp, c.text, c.icon) == ("Edmond", 45, "Fog", "cloud-fog")
    assert c.feels == 38
    assert c.hi_lo == "H:55°  L:40°"
    assert len(c.hours) == 6 and c.hours[0].label == "Now" and c.hours[0].temp == 45
    # "Now" mirrors the observed conditions (Fog), not the hourly forecast's icon.
    assert c.icon == "cloud-fog" and c.hours[0].icon == c.icon
    assert c.hours[1].label == "9AM"
    assert c.wind == "NNE 8"
    assert c.pop == 0 and c.is_day
    assert (c.sunrise.hour, c.sunset.hour) == (6, 17)


def test_stale_observation_falls_back_to_hourly(fake_get):
    obs = load("observation_KPWA.json")
    obs["properties"]["timestamp"] = "2026-11-06T11:00:00+00:00"
    c = fetch(
        fake_get, served(**{"https://api.weather.gov/stations/KPWA/observations/latest": jb(obs)})
    )
    hourly = load("hourly.json")["properties"]["periods"][0]
    assert c.temp == hourly["temperature"] and c.text == hourly["shortForecast"]
    assert c.feels is None


def test_all_stations_null_falls_back_to_hourly(fake_get):
    obs = load("observation_KPWA.json")
    obs["properties"]["temperature"]["value"] = None
    m = served(**{"https://api.weather.gov/stations/KPWA/observations/latest": jb(obs)})
    # The other stations are unmapped (fail), which also counts as unusable.
    c = fetch(fake_get, m)
    assert c.temp == 46 and c.text == "Patchy Fog"


def test_station_list_failure_falls_back(fake_get):
    c = fetch(fake_get, served(**{f"{BASE}/stations": urllib.error.URLError("x")}))
    assert c is not None and c.temp == 46


def test_second_station_used_when_first_fails(fake_get):
    obs = load("observation_KPWA.json")
    obs["properties"]["temperature"]["value"] = 10
    m = served(
        **{
            "https://api.weather.gov/stations/KPWA/observations/latest": urllib.error.URLError("x"),
            "https://api.weather.gov/stations/KGOK/observations/latest": jb(obs),
        }
    )
    assert fetch(fake_get, m).temp == 50


def test_empty_observation_text_uses_hourly_text(fake_get):
    obs = load("observation_KPWA.json")
    obs["properties"]["textDescription"] = ""
    m = served(**{"https://api.weather.gov/stations/KPWA/observations/latest": jb(obs)})
    assert fetch(fake_get, m).text == "Patchy Fog"


def test_feels_like_equal_to_temperature_is_none(fake_get):
    obs = load("observation_KPWA.json")
    obs["properties"]["windChill"]["value"] = 7.2  # 45 F, same as the 7 C reading
    m = served(**{"https://api.weather.gov/stations/KPWA/observations/latest": jb(obs)})
    assert fetch(fake_get, m).feels is None


def test_feels_like_from_heat_index(fake_get):
    obs = load("observation_KPWA.json")
    obs["properties"]["windChill"]["value"] = None
    obs["properties"]["heatIndex"]["value"] = 10
    m = served(**{"https://api.weather.gov/stations/KPWA/observations/latest": jb(obs)})
    assert fetch(fake_get, m).feels == 50


@pytest.mark.parametrize(
    "bad",
    [
        urllib.error.URLError("down"),
        b"not json",
        jb({"properties": {}}),
    ],
)
def test_points_failure_returns_none(fake_get, bad):
    m = served(**{POINTS_URL.format(lat=LAT, lon=LON): bad})
    assert fetch(fake_get, m) is None


def test_forecast_failure_and_no_future_hour_return_none(fake_get):
    assert fetch(fake_get, served(**{f"{BASE}/forecast": urllib.error.URLError("x")})) is None
    assert fetch(fake_get, now=NOW + timedelta(days=5)) is None


def test_night_first_period_uses_next_day_high(fake_get):
    fc = load("forecast.json")
    periods = fc["properties"]["periods"]
    night, day = copy.deepcopy(periods[1]), copy.deepcopy(periods[0])
    day["startTime"] = "2026-11-07T06:00:00-06:00"
    day["temperature"] = 59
    fc["properties"]["periods"] = [night, day]
    c = fetch(fake_get, served(**{f"{BASE}/forecast": jb(fc)}))
    assert c.hi_lo == "L:40° · Sat H:59°"


@pytest.mark.parametrize(
    ("speed", "direction", "expected"),
    [("5 to 10 mph", "S", "S 5–10"), ("0 mph", "N", "Calm"), ("12 mph", "SW", "SW 12")],
)
def test_wind_formats(fake_get, speed, direction, expected):
    fc = load("forecast.json")
    fc["properties"]["periods"][0].update(windSpeed=speed, windDirection=direction)
    assert fetch(fake_get, served(**{f"{BASE}/forecast": jb(fc)})).wind == expected


def test_max_rain_over_next_twelve_hours_and_null_pop(fake_get):
    h = load("hourly.json")
    periods = h["properties"]["periods"]
    periods[3]["probabilityOfPrecipitation"]["value"] = 70
    periods[5]["probabilityOfPrecipitation"] = {"value": None}
    periods[20]["probabilityOfPrecipitation"]["value"] = 99  # beyond the 12-hour window
    c = fetch(fake_get, served(**{f"{BASE}/forecast/hourly": jb(h)}))
    assert c.pop == 70 and c.hours[3].pop == 70 and c.hours[5].pop == 0


def test_hours_start_after_now_when_between_periods(fake_get):
    h = load("hourly.json")
    del h["properties"]["periods"][0]  # now (14:40Z) falls before the first remaining period
    c = fetch(fake_get, served(**{f"{BASE}/forecast/hourly": jb(h)}), now=NOW - timedelta(hours=1))
    assert c.hours[0].label == "Now" and c.hours[1].label == "10AM"


@pytest.mark.parametrize(
    ("day", "rise", "sset"),
    [
        (date(2026, 11, 6), (6, 57), (17, 30)),
        (date(2026, 6, 21), (6, 15), (20, 49)),
    ],
)
def test_sun_times_match_usno(day, rise, sset):
    r, s = sun_times(day, LAT, LON, TZ)
    for got, (h, m) in ((r, rise), (s, sset)):
        want = datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(TZ))
        assert abs(got - want) <= timedelta(minutes=2)


def test_sun_times_stay_on_local_date_far_from_greenwich():
    r, s = sun_times(date(2026, 3, 20), -36.85, 174.76, "Pacific/Auckland")
    assert r.date() == s.date() == date(2026, 3, 20) and r < s
    sun_times(date(2026, 6, 21), 80.0, 20.0, "UTC")  # polar day: clamped, no error


def test_night_is_not_day(fake_get):
    c = fetch(fake_get, now=datetime(2026, 11, 6, 3, 0, tzinfo=UTC))
    assert c is None or not c.is_day  # no hourly period covers 03:00Z in the fixture


@pytest.mark.parametrize(
    ("text", "day", "icon"),
    [
        ("Thunderstorms", True, "cloud-lightning"),
        ("Showers and Thunderstorms", True, "cloud-lightning"),
        ("Light Snow", True, "cloud-snow"),
        ("Freezing Rain", True, "cloud-hail"),
        ("Drizzle", True, "cloud-drizzle"),
        ("Rain", True, "cloud-rain"),
        ("Slight Chance Rain Showers", True, "cloud-rain"),
        ("Patchy Fog then Partly Sunny", True, "cloud-fog"),
        ("Partly Sunny then Patchy Fog", True, "cloud-sun"),
        ("Haze", True, "cloud-fog"),
        ("Mostly Cloudy", True, "cloudy"),
        ("Overcast", False, "cloudy"),
        ("Partly Cloudy", False, "cloud-moon"),
        ("Partly Sunny", True, "cloud-sun"),
        ("Mostly Sunny", True, "cloud-sun"),
        ("Mostly Clear", False, "cloud-moon"),
        ("Sunny", True, "sun"),
        ("Clear", True, "sun"),
        ("Clear", False, "moon"),
        ("Fair", False, "moon"),
        ("A Few Clouds", True, "cloud-sun"),
        ("Breezy and Windy", True, "wind"),
        ("Something Odd", True, "thermometer"),
    ],
)
def test_icon_mapping(text, day, icon):
    assert icon_for(text, day) == icon


def test_every_icon_the_mapping_can_return_exists():
    icons = Path(__file__).parents[1] / "assets" / "icons"
    assert ICON_NAMES
    for name in ICON_NAMES:
        assert (icons / f"{name}.png").exists(), name

"""Opt-in tests that hit the real network: GRAPHICAST_LIVE=1 pytest -m live."""

from __future__ import annotations

import os

import pytest

from graphicast import http
from graphicast.sources import mesonet, nws_xml

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("GRAPHICAST_LIVE") != "1", reason="set GRAPHICAST_LIVE=1"),
]


@pytest.mark.parametrize("module", [mesonet, nws_xml])
def test_live_feed_parses(module) -> None:
    text = http.get_bytes(module.URL.format(office="oun")).decode("utf-8")
    graphics = module.parse(text)
    for g in graphics:
        assert g.image_url.startswith("https://")


def test_live_assess_returns_severity() -> None:
    from graphicast.config import DEFAULT_LAT, DEFAULT_LON
    from graphicast.severity import Severity, assess

    sev = assess([], DEFAULT_LAT, DEFAULT_LON, http.get_bytes)
    assert isinstance(sev, Severity)


def test_live_assess_official_returns_severity() -> None:
    from graphicast.config import DEFAULT_LAT, DEFAULT_LON
    from graphicast.severity import Severity, assess_official

    sev = assess_official(DEFAULT_LAT, DEFAULT_LON, http.get_bytes)
    assert isinstance(sev, Severity) and sev.mentions == ()


def test_live_fetch_conditions_returns_conditions() -> None:
    from datetime import UTC, datetime

    from graphicast.config import DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE_NAME
    from graphicast.schedule import DEFAULT_TZ
    from graphicast.weather import Conditions, fetch_conditions

    c = fetch_conditions(
        DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE_NAME, DEFAULT_TZ, datetime.now(UTC), http.get_bytes
    )
    assert isinstance(c, Conditions) and len(c.hours) >= 1

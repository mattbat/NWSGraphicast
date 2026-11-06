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

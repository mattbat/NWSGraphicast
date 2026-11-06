"""Graphic sources with fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable

from graphicast import http
from graphicast.model import Graphic
from graphicast.sources import mesonet, nws_xml

log = logging.getLogger(__name__)


class AllSourcesFailed(Exception):
    """Every source failed to download or parse."""


SOURCES = [("mesonet", mesonet.URL, mesonet.parse), ("nws_xml", nws_xml.URL, nws_xml.parse)]


def fetch_graphics(
    office: str, get: Callable[..., bytes] = http.get_bytes
) -> tuple[str, list[Graphic]]:
    """Return (source_name, graphics) from the first source that works."""
    errors: list[str] = []
    for name, url_template, parse in SOURCES:
        url = url_template.format(office=office.lower())
        try:
            text = get(url).decode("utf-8")
            return name, parse(text)
        except Exception as exc:
            log.warning("source %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
    raise AllSourcesFailed("; ".join(errors))

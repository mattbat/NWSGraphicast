from __future__ import annotations

import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def FIXTURE_NOW() -> datetime:
    return datetime.fromtimestamp(1793968439, tz=UTC)


@pytest.fixture
def mesonet_text() -> str:
    return (FIXTURES / "mesonet_oun.json").read_text(encoding="utf-8")


@pytest.fixture
def nws_text() -> str:
    return (FIXTURES / "nws_oun.xml").read_text(encoding="utf-8")


@pytest.fixture
def fake_get() -> Callable[[dict], Callable[..., bytes]]:
    def factory(mapping: dict) -> Callable[..., bytes]:
        def get(url: str, timeout: float = 20.0) -> bytes:
            if url not in mapping:
                raise urllib.error.URLError(f"unmapped url: {url}")
            value = mapping[url]
            if isinstance(value, Exception):
                raise value
            return value

        return get

    return factory

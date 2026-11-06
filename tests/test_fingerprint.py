from __future__ import annotations

from datetime import UTC, datetime, timedelta

from graphicast.fingerprint import EMPTY_FINGERPRINT, fingerprint
from graphicast.model import Graphic

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def g(number: int, title: str = "t", desc: str | None = "d") -> Graphic:
    return Graphic(number, number, title, desc, f"https://x/{number}.png", T0, T0 + timedelta(1))


def test_stable_and_hex() -> None:
    fp = fingerprint([g(1), g(2)], {"https://x/1.png": b"a"})
    assert fp == fingerprint([g(1), g(2)], {"https://x/1.png": b"a"})
    assert len(fp) == 64


def test_empty_constant() -> None:
    assert fingerprint([], {}) == EMPTY_FINGERPRINT
    assert len(EMPTY_FINGERPRINT) == 64


def test_order_independent() -> None:
    imgs = {"https://x/1.png": b"a", "https://x/2.png": b"b"}
    assert fingerprint([g(1), g(2)], imgs) == fingerprint([g(2), g(1)], imgs)


def test_image_bytes_sensitive() -> None:
    a = fingerprint([g(1)], {"https://x/1.png": b"a"})
    b = fingerprint([g(1)], {"https://x/1.png": b"b"})
    assert a != b


def test_missing_image_differs_from_present() -> None:
    assert fingerprint([g(1)], {}) != fingerprint([g(1)], {"https://x/1.png": b"a"})


def test_start_end_insensitive() -> None:
    later = Graphic(1, 1, "t", "d", "https://x/1.png", T0 + timedelta(1), T0 + timedelta(9))
    assert fingerprint([g(1)], {}) == fingerprint([later], {})


def test_text_sensitive() -> None:
    assert fingerprint([g(1)], {}) != fingerprint([g(1, title="other")], {})
    assert fingerprint([g(1)], {}) != fingerprint([g(1, desc=None)], {})


def test_unicode() -> None:
    assert len(fingerprint([g(1, title="Frío ☃")], {})) == 64

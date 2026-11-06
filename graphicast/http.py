"""The only module that touches the network."""

from __future__ import annotations

import urllib.request

USER_AGENT = "NWSGraphicast/2.0 (+https://github.com/mattbat/NWSGraphicast)"


def get_bytes(url: str, timeout: float = 20.0) -> bytes:
    """GET a URL. Raises on HTTP errors (urllib default)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def head_ok(url: str, timeout: float = 10.0) -> bool:
    """HTTP HEAD; True on status 200, False on any error."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status == 200
    except OSError:
        return False

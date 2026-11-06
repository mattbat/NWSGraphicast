"""The only module that touches the network."""

from __future__ import annotations

import urllib.request

USER_AGENT = "NWSGraphicast/2.0 (+https://github.com/mattbat/NWSGraphicast)"


def get_bytes(url: str, timeout: float = 20.0) -> bytes:
    """GET a URL. Raises on HTTP errors (urllib default)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()

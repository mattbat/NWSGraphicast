"""Content fingerprint of the active graphic set."""

from __future__ import annotations

import hashlib
import json

from graphicast.model import Graphic


def _digest(items: list[dict]) -> str:
    blob = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


EMPTY_FINGERPRINT = _digest([])


def fingerprint(graphics: list[Graphic], images: dict[str, bytes]) -> str:
    """sha256 over title/description/url/image bytes; ignores start/end and input order."""
    items = [
        {
            "number": g.number,
            "title": g.title,
            "description": g.description,
            "image_url": g.image_url,
            "image_sha256": (
                hashlib.sha256(images[g.image_url]).hexdigest() if g.image_url in images else None
            ),
        }
        for g in sorted(graphics, key=lambda g: g.number)
    ]
    return _digest(items)

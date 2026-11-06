"""Content fingerprint of the active graphic set."""

from __future__ import annotations

import hashlib
import json

from graphicast.model import Graphic


def _digest(items: object) -> str:
    blob = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


EMPTY_FINGERPRINT = _digest([])


def _item(g: Graphic, images: dict[str, bytes]) -> dict:
    """Canonical dict for one graphic (shared by fingerprint and graphic_hashes)."""
    return {
        "number": g.number,
        "title": g.title,
        "description": g.description,
        "image_url": g.image_url,
        "image_sha256": (
            hashlib.sha256(images[g.image_url]).hexdigest() if g.image_url in images else None
        ),
    }


def fingerprint(graphics: list[Graphic], images: dict[str, bytes]) -> str:
    """sha256 over title/description/url/image bytes; ignores start/end and input order."""
    return _digest([_item(g, images) for g in sorted(graphics, key=lambda g: g.number)])


def graphic_hashes(graphics: list[Graphic], images: dict[str, bytes]) -> dict[str, str]:
    """Per-graphic sha256 of the same canonical dict, keyed by str(number)."""
    return {str(g.number): _digest(_item(g, images)) for g in graphics}

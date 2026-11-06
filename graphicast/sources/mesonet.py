"""Oklahoma Mesonet JSON source."""

from __future__ import annotations

import json

from graphicast.model import Graphic, graphic_from_fields

URL = "http://www.mesonet.org/index.php/api/nws_products/graphicast_info/{office}"
NO_IMAGE = "No Image Available"


def parse(text: str) -> list[Graphic]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("mesonet: expected a JSON list")
    graphics: list[Graphic] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("mesonet: expected each entry to be an object")
        if entry.get("Office") == NO_IMAGE:
            continue
        graphics.append(graphic_from_fields(entry))
    return graphics

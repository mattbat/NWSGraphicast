"""weather.gov graphicast XML source."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from graphicast.model import Graphic, graphic_from_fields

URL = "https://www.weather.gov/source/{office}/graphicast/graphicast.xml"


def parse(text: str) -> list[Graphic]:
    root = ET.fromstring(text)
    if root.tag != "graphicasts" and root.find(".//graphicasts") is None:
        raise ValueError("nws_xml: <graphicasts> element not found")
    return [
        graphic_from_fields({child.tag: child.text or "" for child in element})
        for element in root.iter("graphicast")
    ]

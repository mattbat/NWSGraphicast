from __future__ import annotations

import json
import logging
import urllib.error

import pytest

from graphicast.model import active_graphics
from graphicast.sources import SOURCES, AllSourcesFailed, fetch_graphics, mesonet, nws_xml

MESONET_URL = mesonet.URL.format(office="oun")
NWS_URL = nws_xml.URL.format(office="oun")


def test_mesonet_parses(mesonet_text: str) -> None:
    assert len(mesonet.parse(mesonet_text)) == 3


def test_nws_parses_seven(nws_text: str) -> None:
    assert len(nws_xml.parse(nws_text)) == 7


def test_active_numbers_and_order(mesonet_text, nws_text, FIXTURE_NOW) -> None:
    m = active_graphics(mesonet.parse(mesonet_text), FIXTURE_NOW)
    n = active_graphics(nws_xml.parse(nws_text), FIXTURE_NOW)
    assert [g.number for g in m] == [1, 2, 4]
    assert [g.number for g in n] == [1, 2, 4]
    for a, b in zip(m, n, strict=True):
        assert a.title == b.title
        assert a.description == b.description
        assert a.image_url == b.image_url


def test_titles_stripped(mesonet_text, nws_text, FIXTURE_NOW) -> None:
    for parse, text in ((mesonet.parse, mesonet_text), (nws_xml.parse, nws_text)):
        titles = {g.number: g.title for g in active_graphics(parse(text), FIXTURE_NOW)}
        assert titles[1] == "Next 7 Days"
        assert titles[2] == "Friday Morning Fog"
        assert titles[4] == "Cool This Weekend; Warming Next Week"
        for g in parse(text):
            assert g.title == g.title.strip()
            assert g.description is None or g.description == g.description.strip()


def test_image_urls_unescaped(mesonet_text) -> None:
    urls = {g.image_url for g in mesonet.parse(mesonet_text)}
    assert "https://www.weather.gov/images/oun/graphicast/2.png" in urls


def test_nws_none_description_and_loop() -> None:
    xml = """<xml><graphicasts><graphicast>
      <StartTime>1</StartTime><EndTime>2</EndTime><graphicNumber>7</graphicNumber>
      <order>1</order><radar>1</radar><title> T </title><description>none</description>
      <FullImage>https://x/f.png</FullImage><ImageLoop>https://x/l.gif</ImageLoop>
      </graphicast></graphicasts></xml>"""
    (g,) = nws_xml.parse(xml)
    assert g.description is None
    assert g.image_url == "https://x/l.gif"


def test_nws_empty_feed() -> None:
    assert nws_xml.parse("<xml><graphicasts></graphicasts></xml>") == []


def test_nws_missing_graphicasts() -> None:
    with pytest.raises(ValueError, match="graphicasts"):
        nws_xml.parse("<xml><head/></xml>")


def test_nws_bad_xml() -> None:
    with pytest.raises(Exception):  # noqa: B017
        nws_xml.parse("<xml>")


def test_nws_missing_required_field() -> None:
    xml = "<xml><graphicasts><graphicast><title>x</title></graphicast></graphicasts></xml>"
    with pytest.raises(ValueError, match="graphicNumber"):
        nws_xml.parse(xml)


def test_mesonet_empty_list() -> None:
    assert mesonet.parse("[]") == []


def test_mesonet_no_image_available() -> None:
    assert mesonet.parse(json.dumps([{"Office": "No Image Available"}])) == []


def test_mesonet_not_a_list() -> None:
    with pytest.raises(ValueError, match="list"):
        mesonet.parse('{"a": 1}')


def test_mesonet_entry_not_object() -> None:
    with pytest.raises(ValueError, match="object"):
        mesonet.parse("[1]")


def test_mesonet_invalid_json() -> None:
    with pytest.raises(ValueError):
        mesonet.parse("not json")


def test_mesonet_bad_fields() -> None:
    entry = {"graphicNumber": "x", "StartTime": "1", "EndTime": "2", "FullImage": "u"}
    with pytest.raises(ValueError, match="graphicNumber"):
        mesonet.parse(json.dumps([entry]))


def test_sources_order() -> None:
    assert [s[0] for s in SOURCES] == ["mesonet", "nws_xml"]


def test_fetch_uses_mesonet_first(fake_get, mesonet_text, nws_text) -> None:
    get = fake_get({MESONET_URL: mesonet_text.encode(), NWS_URL: nws_text.encode()})
    name, graphics = fetch_graphics("oun", get)
    assert name == "mesonet"
    assert len(graphics) == 3


def test_fetch_lowercases_office(fake_get, mesonet_text) -> None:
    name, _ = fetch_graphics("OUN", fake_get({MESONET_URL: mesonet_text.encode()}))
    assert name == "mesonet"


def test_fallback_on_download_error(fake_get, nws_text, caplog) -> None:
    get = fake_get({MESONET_URL: urllib.error.URLError("boom"), NWS_URL: nws_text.encode()})
    with caplog.at_level(logging.WARNING):
        name, graphics = fetch_graphics("oun", get)
    assert name == "nws_xml"
    assert len(graphics) == 7
    assert "mesonet" in caplog.text


def test_fallback_on_parse_error(fake_get, nws_text) -> None:
    get = fake_get({MESONET_URL: b"garbage", NWS_URL: nws_text.encode()})
    assert fetch_graphics("oun", get)[0] == "nws_xml"


def test_empty_list_is_success(fake_get, nws_text) -> None:
    get = fake_get({MESONET_URL: b"[]", NWS_URL: nws_text.encode()})
    assert fetch_graphics("oun", get) == ("mesonet", [])


def test_all_fail(fake_get) -> None:
    get = fake_get({MESONET_URL: OSError("a"), NWS_URL: b"<bad"})
    with pytest.raises(AllSourcesFailed) as exc:
        fetch_graphics("oun", get)
    assert "mesonet" in str(exc.value) and "nws_xml" in str(exc.value)


def test_fake_get_unmapped_raises_urlerror(fake_get) -> None:
    with pytest.raises(urllib.error.URLError):
        fake_get({})("http://nope", timeout=1)

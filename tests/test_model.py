from __future__ import annotations

from datetime import UTC, datetime

import pytest

from graphicast.model import Graphic, active_graphics, graphic_from_fields


def fields(**over: str) -> dict[str, str]:
    base = {
        "graphicNumber": "3",
        "order": "5",
        "title": "  Hello \n",
        "description": "\n desc  ",
        "FullImage": "https://x/3.png",
        "ImageLoop": "",
        "radar": "0",
        "StartTime": "1000",
        "EndTime": "2000",
    }
    base.update(over)
    return base


def at(sec: int) -> datetime:
    return datetime.fromtimestamp(sec, tz=UTC)


def test_basic_build_strips() -> None:
    g = graphic_from_fields(fields())
    assert (g.number, g.order, g.title, g.description) == (3, 5, "Hello", "desc")
    assert g.start == at(1000) and g.end == at(2000)
    assert g.start.tzinfo is not None
    assert g.image_url == "https://x/3.png"


@pytest.mark.parametrize("desc", ["none", "None", " NONE\n", "", "   "])
def test_description_none(desc: str) -> None:
    assert graphic_from_fields(fields(description=desc)).description is None


def test_missing_description_key() -> None:
    f = fields()
    del f["description"]
    assert graphic_from_fields(f).description is None


def test_radar_loop_selected() -> None:
    g = graphic_from_fields(fields(radar="1", ImageLoop="https://x/loop.gif"))
    assert g.image_url == "https://x/loop.gif"


def test_radar_with_empty_loop_uses_full() -> None:
    assert graphic_from_fields(fields(radar="1")).image_url == "https://x/3.png"


def test_loop_ignored_when_not_radar() -> None:
    g = graphic_from_fields(fields(ImageLoop="https://x/loop.gif"))
    assert g.image_url == "https://x/3.png"


def test_missing_order_defaults_to_number() -> None:
    f = fields()
    del f["order"]
    assert graphic_from_fields(f).order == 3


def test_unicode_title() -> None:
    g = graphic_from_fields(fields(title="Frío – 30°F ☃"))
    assert g.title == "Frío – 30°F ☃"


@pytest.mark.parametrize("key", ["graphicNumber", "StartTime", "EndTime", "FullImage"])
def test_missing_required(key: str) -> None:
    f = fields()
    del f[key]
    with pytest.raises(ValueError, match=key):
        graphic_from_fields(f)


@pytest.mark.parametrize("key", ["graphicNumber", "StartTime", "EndTime", "order"])
def test_non_numeric(key: str) -> None:
    with pytest.raises(ValueError, match=key):
        graphic_from_fields(fields(**{key: "abc"}))


def test_out_of_range_timestamp() -> None:
    with pytest.raises(ValueError, match="StartTime"):
        graphic_from_fields(fields(StartTime="99999999999999999999"))


def test_empty_required_value() -> None:
    with pytest.raises(ValueError, match="FullImage"):
        graphic_from_fields(fields(FullImage="  "))


def make(number: int, order: int, start: int = 1000, end: int = 2000) -> Graphic:
    return Graphic(number, order, "t", None, "u", at(start), at(end))


def test_is_active_boundaries() -> None:
    g = make(1, 1)
    assert g.is_active(at(1000))
    assert g.is_active(at(1999))
    assert not g.is_active(at(2000))
    assert not g.is_active(at(999))


def test_active_graphics_sorted_and_filtered() -> None:
    gs = [make(3, 1), make(1, 2), make(2, 1), make(9, 0, 0, 500)]
    result = active_graphics(gs, at(1500))
    assert [g.number for g in result] == [2, 3, 1]


def test_active_graphics_empty() -> None:
    assert active_graphics([], at(1)) == []

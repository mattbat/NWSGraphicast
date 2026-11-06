from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from graphicast.weather import Conditions, Hour
from graphicast.widget import gradient, icon_names, widget_html, widget_plain
from tests.test_render import NOW, g, html_of, preview_of, render

CST = ZoneInfo("America/Chicago")


def conditions(**over) -> Conditions:
    base = dict(
        place="Edmond",
        temp=45,
        text="Fog",
        icon="cloud-fog",
        feels=38,
        hi_lo="H:55°  L:40°",
        hours=(
            Hour("Now", "cloud-fog", 45, 0),
            Hour("9AM", "cloudy", 48, 0),
            Hour("10AM", "cloud-sun", 50, 0),
            Hour("11AM", "cloud-sun", 51, 0),
            Hour("12PM", "cloudy", 53, 0),
            Hour("1PM", "cloudy", 53, 0),
        ),
        sunrise=datetime(2026, 11, 6, 6, 56, tzinfo=CST),
        sunset=datetime(2026, 11, 6, 17, 30, tzinfo=CST),
        wind="NNE 8",
        pop=0,
        is_day=True,
    )
    base.update(over)
    return Conditions(**base)


def test_plain_line_matches_spec():
    assert widget_plain(conditions()) == (
        "Edmond 45° Fog (feels 38°) · H:55° L:40° · Sunrise 6:56 AM · Sunset 5:30 PM · "
        "Wind NNE 8 mph · Rain 0%"
    )
    line = widget_plain(conditions(feels=None, wind="Calm", pop=30))
    assert "feels" not in line and "Wind Calm ·" in line and line.endswith("Rain 30%")


def test_gradient_rules():
    assert gradient("Thunderstorms", True) == ("#3d4b5f", "#5f7189")
    assert gradient("Fog", True) == ("#5d7590", "#8fa6be")
    assert gradient("Fog", False) == ("#5d7590", "#2b3a52")
    assert gradient("Sunny", True) == ("#2f7fd8", "#69b2f0")
    assert gradient("Clear", False) == ("#0e1a3a", "#2b3d6b")


def test_widget_html_contents_and_rain_line():
    src = lambda n: f"https://h/{n}.png"  # noqa: E731
    dry = widget_html(conditions(), src)
    assert "Feels like 38°" in dry and "H:55°&nbsp; L:40°" in dry
    assert 'alt=""' in dry and "https://h/navigation.png" in dry
    assert "#a9dcff" not in dry and "class=" not in dry  # no rain line, no dark-mode classes
    hours = list(conditions().hours)
    hours[2] = Hour("10AM", "cloud-rain", 50, 40)
    wet = widget_html(conditions(hours=tuple(hours), pop=40), src)
    assert wet.count("#a9dcff") == 1 and ">40%<" in wet and wet.count("&nbsp;</div>") >= 5
    assert "Feels like" not in widget_html(conditions(feels=None), src)


def test_icon_names_are_distinct():
    names = icon_names(conditions())
    assert len(names) == len(set(names)) and "cloudy" in names and "droplet" in names


def test_widget_after_header_before_graphics():
    html = html_of(render([g()], {}, conditions=conditions(), asset_base_url="https://a/icons"))
    assert html.index("GRAPHICAST") < html.index("Feels like") < html.index(">Title<")


def test_no_conditions_no_widget():
    msg = render([g()], {})
    assert "Feels like" not in html_of(msg) and "Sunrise" not in msg.get_body().get_content()
    assert "Feels like" not in preview_of([g()], {})


def test_hosted_icon_urls():
    html = html_of(render([g()], {}, conditions=conditions(), asset_base_url="https://a/i/"))
    assert 'src="https://a/i/cloud-fog.png"' in html and "cid:" not in html


def test_inline_mode_attaches_each_icon_once():
    c = conditions()
    msg = render([g()], {}, conditions=c)
    cids = [p["Content-ID"] for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(cids) == len(icon_names(c)) == len(set(cids))
    html = html_of(msg)
    assert all(f"cid:{cid[1:-1]}" in html for cid in cids)
    assert html.count('src="cid:') > len(cids)  # cloudy/cloud-sun appear several times


def test_preview_uses_data_uris():
    html = preview_of([g()], {}, conditions=conditions())
    assert re.search(r'src="data:image/png;base64,[A-Za-z0-9+/=]+"', html)
    assert "cid:" not in html


def test_plain_text_part_has_widget_line_after_banner():
    msg = render([g()], {}, conditions=conditions())
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert text.startswith("Edmond 45° Fog (feels 38°)")


def test_feed_text_escaped_in_widget():
    c = conditions(text="<b>Fog</b>", place="<i>x</i>")
    html = html_of(render([g()], {}, conditions=c, asset_base_url="https://a"))
    assert "<b>Fog</b>" not in html and "&lt;b&gt;Fog&lt;/b&gt;" in html
    assert "<i>x</i>" not in html


def test_widget_text_survives_without_images():
    html = preview_of([g()], {}, conditions=replace(conditions(), temp=77))
    assert "77°" in html and NOW.tzinfo is UTC

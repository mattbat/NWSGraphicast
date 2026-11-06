from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

from graphicast.model import Graphic
from graphicast.severity import (
    ALERTS_FALLBACK_URL,
    ALERTS_URL,
    SPC_URL,
    Alert,
    Outlook,
    Severity,
    assess,
    find_mentions,
    parse_alerts,
    parse_spc,
    point_in_geometry,
    severity_rose,
    snapshot,
)

FIXTURES = Path(__file__).parent / "fixtures"
EDMOND = (35.6528, -97.4781)  # (lat, lon)
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


# --- geometry -------------------------------------------------------------------------------


def test_point_inside_and_outside_square():
    poly = {"type": "Polygon", "coordinates": [square(-100, 30, -90, 40)]}
    assert point_in_geometry(-95, 35, poly)
    assert not point_in_geometry(-85, 35, poly)
    assert not point_in_geometry(-95, 45, poly)


def test_point_in_hole_is_outside():
    poly = {
        "type": "Polygon",
        "coordinates": [square(-100, 30, -90, 40), square(-97, 33, -93, 37)],
    }
    assert not point_in_geometry(-95, 35, poly)
    assert point_in_geometry(-98.5, 35, poly)


def test_multipolygon_second_polygon():
    multi = {
        "type": "MultiPolygon",
        "coordinates": [[square(0, 0, 1, 1)], [square(-100, 30, -90, 40)]],
    }
    assert point_in_geometry(-95, 35, multi)
    assert not point_in_geometry(-50, 35, multi)


def test_point_near_edge():
    poly = {"type": "Polygon", "coordinates": [square(-100, 30, -90, 40)]}
    assert point_in_geometry(-90.0001, 39.9999, poly)
    assert not point_in_geometry(-89.9999, 39.9999, poly)
    assert not point_in_geometry(-95, 40.0001, poly)


def test_unsupported_or_empty_geometry():
    assert not point_in_geometry(0, 0, {"type": "Point", "coordinates": [0, 0]})
    assert not point_in_geometry(0, 0, {"type": "Polygon", "coordinates": []})
    assert not point_in_geometry(0, 0, {})


# --- SPC ------------------------------------------------------------------------------------


def spc_json(*levels):
    """Nested squares around Edmond, outermost first."""
    features = []
    for i, label in enumerate(levels):
        pad = 10 - 3 * i
        geom = {
            "type": "Polygon",
            "coordinates": [square(-97.4781 - pad, 35.6528 - pad, -97.4781 + pad, 35.6528 + pad)],
        }
        props = {"LABEL": label, "VALID_ISO": "2026-11-07T12:00:00+00:00"}
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": features})


def test_real_fixture_atlantic_is_none():
    text = (FIXTURES / "spc_day1_20261106.geojson").read_text()
    assert parse_spc(text, 1, 30.0, -60.0) is None


def test_real_fixture_edmond_is_none_and_marginal_elsewhere():
    day1 = (FIXTURES / "spc_day1_20261106.geojson").read_text()
    day2 = (FIXTURES / "spc_day2_20261106.geojson").read_text()
    assert parse_spc(day1, 1, *EDMOND) is None  # the day-1 Marginal area is far from Edmond
    assert parse_spc(day2, 2, *EDMOND) is None  # day 2 is TSTM only
    found = parse_spc(day1, 1, 34.0, -80.0)  # inside the day-1 Marginal area
    assert found == Outlook(1, 1, "Marginal", datetime(2026, 11, 6, 13, 0, tzinfo=UTC))


def test_nested_levels_return_highest():
    out = parse_spc(spc_json("MRGL", "SLGT", "ENH"), 2, *EDMOND)
    assert out is not None and (out.level, out.name, out.day) == (3, "Enhanced", 2)
    assert out.valid == datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def test_highest_level_wins_regardless_of_feature_order():
    out = parse_spc(spc_json("ENH", "SLGT"), 1, *EDMOND)
    assert out is not None and out.level == 3


def test_tstm_only_is_none():
    assert parse_spc(spc_json("TSTM"), 1, *EDMOND) is None


# --- alerts ---------------------------------------------------------------------------------


def alerts_json(*events):
    feats = [{"properties": {"event": e, "headline": f"{e} headline"}} for e in events]
    return json.dumps({"type": "FeatureCollection", "features": feats})


def test_alerts_keep_watches_and_warnings_only():
    text = alerts_json("Tornado Watch", "Wind Advisory", "Winter Storm Warning")
    assert parse_alerts(text) == (
        Alert("Tornado Watch", "Tornado Watch headline", ALERTS_FALLBACK_URL),
        Alert("Winter Storm Warning", "Winter Storm Warning headline", ALERTS_FALLBACK_URL),
    )


def test_alerts_deduplicated_and_irrelevant_dropped():
    text = alerts_json("Tornado Watch", "Tornado Watch", "Red Flag Warning", "Frost Advisory")
    assert [a.event for a in parse_alerts(text)] == ["Tornado Watch"]


def test_alert_without_headline():
    text = json.dumps({"features": [{"properties": {"event": "Flash Flood Warning"}}]})
    assert parse_alerts(text) == (Alert("Flash Flood Warning", "", ALERTS_FALLBACK_URL),)


# --- mentions -------------------------------------------------------------------------------


def gfx(title="T", desc=None):
    return Graphic(1, 1, title, desc, "https://x/1.png", NOW, NOW)


def test_mention_negated_tornadoes():
    assert find_mentions([gfx(desc="Tornadoes are not expected.")]) == ()


def test_mention_negated_severe_weather():
    assert find_mentions([gfx(desc="No severe weather is anticipated.")]) == ()


def test_mention_tornadoes_possible():
    assert find_mentions([gfx(desc="A few tornadoes are possible Saturday evening.")]) == (
        "tornadoes",
    )


def test_mention_hail_and_winds():
    text = "Large hail and damaging winds are the main threats."
    assert find_mentions([gfx(desc=text)]) == ("large hail", "damaging winds")


def test_mention_negation_in_same_sentence_skips_all():
    """The whole sentence is skipped when it holds a negation, so even the affirmative
    "Severe storms possible" yields nothing: the rule is per sentence, not per phrase."""
    assert find_mentions([gfx(desc="Severe storms possible; tornadoes unlikely.")]) == ()


def test_mention_snow_and_blizzard_in_text_order():
    assert find_mentions([gfx(desc="Heavy snow and blizzard conditions.")]) == (
        "heavy snow",
        "blizzard",
    )


def test_mention_sentences_split_and_dedup_and_titles():
    g = gfx(title="Tornado Outlook", desc="Tornadoes likely.\nNo hail. Freezing rain too!")
    assert find_mentions([g, gfx(desc="Flash flooding possible. Tornadoes again.")]) == (
        "tornadoes",
        "ice",
        "flash flooding",
    )


# --- assess ---------------------------------------------------------------------------------


def make_get(mapping):
    def get(url, timeout=20.0):
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        return value.encode()

    return get


def full_map(**over):
    m = {
        SPC_URL.format(day=1): spc_json("MRGL"),
        SPC_URL.format(day=2): spc_json("MRGL", "SLGT", "ENH"),
        SPC_URL.format(day=3): spc_json("TSTM"),
        ALERTS_URL.format(lat=EDMOND[0], lon=EDMOND[1]): alerts_json("Tornado Watch"),
    }
    m.update(over)
    return m


def test_assess_all_sources_ok():
    sev = assess([gfx(desc="Large hail possible.")], *EDMOND, make_get(full_map()))
    assert sev.ok and sev.max_level == 3 and sev.flagged
    assert [(o.day, o.level) for o in sev.outlooks] == [(1, 1), (2, 3)]
    assert [a.event for a in sev.alerts] == ["Tornado Watch"]
    assert sev.mentions == ("large hail",)


def test_assess_one_spc_day_fails_others_used():
    err = urllib.error.URLError("down")
    sev = assess([], *EDMOND, make_get(full_map(**{SPC_URL.format(day=2): err})))
    assert not sev.ok and [o.day for o in sev.outlooks] == [1]
    assert sev.alerts


def test_assess_alerts_fail():
    url = ALERTS_URL.format(lat=EDMOND[0], lon=EDMOND[1])
    sev = assess([], *EDMOND, make_get(full_map(**{url: OSError("x")})))
    assert not sev.ok and sev.alerts == () and sev.max_level == 3


def test_assess_garbage_payload_never_raises():
    bad = {k: "not json" for k in full_map()}
    sev = assess([], *EDMOND, make_get(bad))
    assert sev == Severity(ok=False)


def test_assess_nothing_active_is_ok_and_unflagged():
    quiet = {k: json.dumps({"features": []}) for k in full_map()}
    sev = assess([], *EDMOND, make_get(quiet))
    assert sev.ok and not sev.flagged and sev.max_level == 0


# --- state helpers --------------------------------------------------------------------------


def sev_of(level=0, alerts=(), ok=True):
    outlooks = (Outlook(1, level, "X", NOW),) if level else ()
    return Severity(outlooks, tuple(Alert(a, "") for a in alerts), (), ok)


def test_snapshot():
    assert snapshot(sev_of(3, ["B", "A"])) == {"max_level": 3, "alerts": ["A", "B"]}


@pytest.mark.parametrize(
    ("sev", "saved", "rose"),
    [
        (sev_of(2), None, False),
        (sev_of(2), {"max_level": 1}, False),  # malformed baseline
        (sev_of(2), {"max_level": 1, "alerts": []}, True),
        (sev_of(2), {"max_level": 2, "alerts": []}, False),
        (sev_of(1), {"max_level": 3, "alerts": []}, False),
        (sev_of(1), {"max_level": 0, "alerts": []}, False),  # Marginal alone
        (sev_of(0, ["Tornado Watch"]), {"max_level": 0, "alerts": []}, True),
        (sev_of(0, ["Tornado Watch"]), {"max_level": 0, "alerts": ["Tornado Watch"]}, False),
        (sev_of(3, ok=False), {"max_level": 0, "alerts": []}, False),
    ],
)
def test_severity_rose(sev, saved, rose):
    assert severity_rose(sev, saved) is rose


def test_assess_official_has_no_mentions_and_with_mentions_adds_them():
    from graphicast.severity import assess_official, with_mentions

    graphics = [gfx(desc="Large hail possible.")]
    official = assess_official(*EDMOND, make_get(full_map()))
    assert official.mentions == () and official.ok
    assert with_mentions(official, graphics).mentions == ("large hail",)


def test_alert_url_from_feature_id_or_at_id():
    api = "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.abc"
    feats = [
        {"id": api, "properties": {"event": "Tornado Watch", "@id": "other"}},
        {"properties": {"event": "Flash Flood Warning", "@id": api + "2"}},
    ]
    alerts = parse_alerts(json.dumps({"features": feats}))
    assert [a.url for a in alerts] == [api, api + "2"]


def test_alert_url_default_empty_and_snapshot_unchanged():
    assert Alert("A", "h").url == ""
    sev = Severity(alerts=(Alert("A", "h", "https://x"),))
    assert snapshot(sev) == {"max_level": 0, "alerts": ["A"]}

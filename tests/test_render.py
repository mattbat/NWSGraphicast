from __future__ import annotations

import email
from datetime import UTC, datetime
from email import policy

from graphicast.model import Graphic
from graphicast.render import (
    format_subject,
    format_valid_until,
    image_type,
    render_email,
    render_html_preview,
    subject_lead,
)
from graphicast.severity import Alert, Outlook, Severity

PNG = b"\x89PNG\r\n\x1a\n" + b"x"
NOW = datetime(2026, 11, 6, 11, 14, tzinfo=UTC)


def g(number=1, title="Title", desc="Desc", url="https://x/1.png") -> Graphic:
    return Graphic(number, number, title, desc, url, NOW, NOW)


def render(graphics, images, **kw):
    return render_email(
        office="oun",
        office_name="Norman",
        graphics=graphics,
        images=images,
        now=NOW,
        tz="America/Chicago",
        sender="a@example.com",
        to="b@example.com",
        **kw,
    )


def preview_of(graphics, images, **kw) -> str:
    return render_html_preview(
        office="oun",
        office_name="Norman",
        graphics=graphics,
        images=images,
        now=NOW,
        tz="America/Chicago",
        **kw,
    )


def html_of(msg) -> str:
    return msg.get_body(preferencelist=("html",)).get_content()


def test_subject_format():
    assert (
        format_subject("oun", NOW, "America/Chicago") == "NWS OUN Graphicast — Fri Nov 6, 5:14 AM"
    )
    pm = datetime(2026, 7, 4, 23, 5, tzinfo=UTC)
    assert format_subject("oun", pm, "America/Chicago") == "NWS OUN Graphicast — Sat Jul 4, 6:05 PM"


def test_headers_and_structure():
    msg = render([g()], {"https://x/1.png": PNG})
    assert msg["From"] == "a@example.com"
    assert msg["To"] == "b@example.com"
    assert msg["Date"] == "Fri, 06 Nov 2026 11:14:00 +0000"
    assert msg.get_content_type() == "multipart/alternative"
    kinds = [p.get_content_type() for p in msg.iter_parts()]
    assert kinds == ["text/plain", "multipart/related"]
    related = list(msg.iter_parts())[1]
    assert [p.get_content_type() for p in related.iter_parts()] == ["text/html", "image/png"]


def test_cid_matches_image_part():
    msg = render([g()], {"https://x/1.png": PNG})
    img = [p for p in msg.walk() if p.get_content_maintype() == "image"][0]
    cid = img["Content-ID"].strip("<>")
    assert f'src="cid:{cid}"' in html_of(msg)
    assert img.get_content() == PNG


def test_message_roundtrips():
    msg = render([g()], {"https://x/1.png": PNG})
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert parsed["Subject"] == msg["Subject"]


def test_missing_image_links_by_url():
    msg = render([g(1), g(2, url="https://x/2.png")], {"https://x/1.png": PNG})
    html = html_of(msg)
    assert 'src="https://x/2.png"' in html
    assert "cid:" in html
    assert len([p for p in msg.walk() if p.get_content_maintype() == "image"]) == 1


def test_plain_text_content():
    msg = render([g(title="Fog", desc="Dense")], {})
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Fog" in text and "Dense" in text and "https://x/1.png" in text
    assert "View on weather.gov: https://x/1.png" in text and "Valid until" in text
    assert "https://www.weather.gov/oun" in text
    assert "https://www.spc.noaa.gov/" in text


def test_no_description_omits_paragraph():
    html = html_of(render([g(desc=None)], {}))
    assert 'class="c-body"' not in html


def test_html_escapes_feed_text():
    bad = g(title='<script>alert(1)</script> & "q"', desc="<b>x</b>")
    html = html_of(render([bad], {}))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "&quot;q&quot;" in html
    preview = preview_of([bad], {})
    assert "<script>" not in preview
    assert "&lt;script&gt;" in preview
    plain_html = html_of(render([bad], {}, new_numbers=frozenset({1})))
    assert "<script>" not in plain_html


def test_unicode_text():
    msg = render([g(title="Café ☃ — 天気", desc="über")], {})
    assert "天気" in html_of(msg)
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert "☃" in parsed.get_body(preferencelist=("plain",)).get_content()


def test_footer_links():
    html = html_of(render([g()], {}))
    assert 'href="https://www.weather.gov/oun"' in html
    assert "NWS Norman" in html
    assert 'href="https://www.spc.noaa.gov/"' in html
    assert "Storm Prediction Center" in html


def test_image_type_sniffing():
    assert image_type(PNG) == ("image", "png")
    assert image_type(b"GIF89a...") == ("image", "gif")
    assert image_type(b"\xff\xd8\xff\xe0") == ("image", "jpeg")
    assert image_type(b"junk") == ("application", "octet-stream")


def test_gif_loop_and_octet_stream_parts():
    gif = g(1, url="https://x/loop.gif")
    odd = g(2, url="https://x/odd.bin")
    msg = render([gif, odd], {gif.image_url: b"GIF89a123", odd.image_url: b"???"})
    types = [p.get_content_type() for p in msg.walk() if p.get_content_maintype() != "multipart"]
    assert "image/gif" in types
    assert "application/octet-stream" in types


def test_hosted_mode_no_attachments():
    a, b = g(1), g(2, url="https://x/2.png")
    hosted = {a.image_url: "https://h/f/1.jpg", b.image_url: "https://h/f/2.jpg"}
    msg = render([a, b], {a.image_url: PNG, b.image_url: PNG}, hosted_urls=hosted)
    assert [p for p in msg.walk() if p.get_content_maintype() == "image"] == []
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]
    html = html_of(msg)
    assert 'src="https://h/f/1.jpg"' in html and 'src="https://h/f/2.jpg"' in html
    assert "cid:" not in html and 'width="100%"' in html
    assert 'href="https://x/1.png"' in html and "View on weather.gov" in html
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "https://h/f/1.jpg" in text and "https://x/1.png" in text
    assert len(msg.as_bytes()) < 50_000


def test_hosted_mode_unhosted_graphic_links_nws_url():
    a, b = g(1), g(2, url="https://x/2.png")
    msg = render([a, b], {}, hosted_urls={a.image_url: "https://h/f/1.jpg"})
    assert 'src="https://x/2.png"' in html_of(msg)


def test_nws_link_in_inline_mode():
    html = html_of(render([g()], {}))
    assert 'href="https://x/1.png"' in html and "View on weather.gov" in html


def test_same_url_shared_cid():
    a, b = g(1), g(2)
    msg = render([a, b], {a.image_url: PNG})
    assert len([p for p in msg.walk() if p.get_content_maintype() == "image"]) == 1


def test_preview_data_uris():
    a, b = g(1), g(2, url="https://x/2.png")
    html = preview_of([a, b], {a.image_url: PNG})
    assert "data:image/png;base64," in html
    assert 'src="https://x/2.png"' in html


# --- Change 2: premium design -------------------------------------------------------------


def graphic_ending(number, end, title="Title"):
    return Graphic(number, number, title, "Desc", f"https://x/{number}.png", NOW, end)


def test_design_tokens_present():
    html = html_of(render([g()], {}))
    assert "background:#ffffff" in html and "#f7fafb" not in html
    assert "border-bottom:3px solid #f5a524" in html and "border-radius:12px" in html
    assert "padding:11px 14px" in html
    assert "NWS NORMAN &middot; GRAPHICAST" in html
    assert "Fri Nov 6 \u00b7 5:14 AM" in html
    assert "Forecast update" not in html and "linear-gradient" not in html


def test_dark_mode_and_color_scheme_metas():
    html = html_of(render([g()], {}))
    assert "@media (prefers-color-scheme: dark)" in html
    for token in ("#0f1318", "#26303c", "#e8eef6", "#c3cfdd", "#8b9bb0", "#8ab4ff"):
        assert token in html
    assert "#3a2a0a" in html and "#fcd34d" in html
    assert '<meta name="color-scheme" content="light dark">' in html
    assert '<meta name="supported-color-schemes" content="light dark">' in html
    assert "<script" not in html and "@import" not in html


def test_preheader_orders_new_first():
    a, b, c = g(1, title="Alpha"), g(2, title="Beta"), g(3, title="Gamma")
    html = html_of(render([a, b, c], {}, new_numbers=frozenset({3})))
    assert "New: Gamma \u00b7 Alpha \u00b7 Beta" in html
    assert "display:none;max-height:0;overflow:hidden;opacity:0" in html
    assert html.count("&#8203;&nbsp;") >= 60
    assert html.index("New: Gamma") < html.index("GRAPHICAST")


def test_new_badge_only_on_new_graphics():
    html = html_of(render([g(1), g(2, url="https://x/2.png")], {}, new_numbers=frozenset({2})))
    assert html.count(">NEW</span>") == 1
    assert ">NEW</span>" not in html_of(render([g(1)], {}))
    text = render([g(1, title="One"), g(2, title="Two")], {}, new_numbers=frozenset({2}))
    plain = text.get_body(preferencelist=("plain",)).get_content()
    assert "[NEW] Two" in plain and "[NEW] One" not in plain


def test_valid_until_cst_and_cdt():
    cst = datetime(2026, 11, 7, 11, 14, tzinfo=UTC)  # Sat 5:14 AM CST
    cdt = datetime(2026, 7, 4, 23, 5, tzinfo=UTC)  # Sat 6:05 PM CDT
    assert format_valid_until(cst, "America/Chicago") == "Sat 5:14 AM"
    assert format_valid_until(cdt, "America/Chicago") == "Sat 6:05 PM"
    html = html_of(render([graphic_ending(1, cst), graphic_ending(2, cdt)], {}))
    assert "Valid until Sat 5:14 AM" in html and "Valid until Sat 6:05 PM" in html
    plain = render([graphic_ending(1, cst)], {}).get_body(preferencelist=("plain",)).get_content()
    assert "Valid until Sat 5:14 AM" in plain


def test_header_has_no_graphic_count():
    three = [g(1), g(2, url="https://x/2.png"), g(3, url="https://x/3.png")]
    for graphics in ([g(1)], three):
        html = html_of(render(graphics, {}))
        assert "1 graphic" not in html and "3 graphics" not in html


def test_alt_fallback_text():
    html = html_of(render([g(title='A "b"')], {}))
    assert 'alt="A &quot;b&quot; (image unavailable, see weather.gov link below)"' in html
    assert "font-size:13px;color:#7a8594" in html


def test_images_expire_text_only_in_hosted_mode():
    a = g(1)
    inline = html_of(render([a], {}))
    assert "Sent when NWS Norman updates its graphics" in inline
    assert "images expire" not in inline
    hosted = html_of(render([a], {}, hosted_urls={a.image_url: "https://h/1.jpg"}, image_days=5))
    assert "images expire after 5 days" in hosted
    text = render([a], {}, hosted_urls={a.image_url: "https://h/1.jpg"}, image_days=5)
    assert "images expire after 5 days" in text.get_body(preferencelist=("plain",)).get_content()


def test_script_escaped_in_preheader_and_alt():
    bad = g(title="<script>x</script>", desc="<script>y</script>")
    for html in (
        html_of(render([bad], {}, new_numbers=frozenset({1}))),
        preview_of([bad], {}, new_numbers=frozenset({1})),
    ):
        assert "<script>" not in html
        assert "New: &lt;script&gt;x&lt;/script&gt;" in html
        assert "&lt;script&gt;x&lt;/script&gt; (image unavailable" in html


def test_office_name_escaped_and_uppercased():
    msg = render_email(
        office="tul",
        office_name="Tulsa <OK>",
        graphics=[g()],
        images={},
        now=NOW,
        tz="America/Chicago",
        sender="a@example.com",
        to="b@example.com",
    )
    html = html_of(msg)
    assert "NWS TULSA &lt;OK&gt; &middot; GRAPHICAST" in html
    assert 'href="https://www.weather.gov/tul"' in html


# --- Change 3: layout B, compact header, severity banner -----------------------------------


def outlook(level=3, name="Enhanced", day=2, valid=None):
    valid = valid or datetime(2026, 11, 7, 12, 0, tzinfo=UTC)  # Saturday local
    return Outlook(day, level, name, valid)


def test_layout_b_has_no_cards_and_full_width_image():
    html = html_of(render([g()], {}))
    assert "box-shadow" not in html and "bg-card" not in html
    assert "border:1px solid #e4eaee" not in html
    assert 'style="padding:0"><img' in html
    assert "display:block;width:100%;height:auto;border:0" in html
    assert "border-radius:10px" not in html
    assert "padding:8px 10px 22px;border-bottom:1px solid #e4eaee" in html
    assert "padding:4px 10px 10px" in html and "font-size:18px;font-weight:700" in html
    assert 'class="bd-line"' in html


def test_no_severity_means_no_banner_and_amber_header_border():
    html = html_of(render([g()], {}, severity=Severity()))
    assert 'class="bn-' not in html
    assert "border-bottom:3px solid #f5a524" in html
    assert render([g()], {}, severity=Severity())["Subject"].startswith("NWS OUN")


def test_warning_banner_for_flagged_outlook():
    sev = Severity(outlooks=(outlook(),), mentions=("tornadoes", "large hail"))
    msg = render([g()], {}, severity=sev)
    html = html_of(msg)
    assert 'class="bn-warn"' in html and "background:#fff4e5" in html
    assert "border:1px solid #f3c27a" in html and "#b42318" in html
    assert "\u26a0\ufe0f Enhanced Risk (3/5) of severe storms, Saturday" in html
    assert "Storm Prediction Center Day 2 outlook covers Edmond." in html
    assert "Graphics mention: tornadoes, large hail" in html
    assert "border-bottom:3px solid #f5a524" not in html
    assert "border-radius:12px 12px 0 0" in html
    assert msg["Subject"].startswith(
        "\u26a0\ufe0f Enhanced Risk Saturday \u00b7 NWS OUN Graphicast"
    )


def test_warning_banner_for_alert_only():
    sev = Severity(alerts=(Alert("Tornado Watch", "Tornado Watch until 9 PM"),))
    msg = render([g()], {}, severity=sev)
    html = html_of(msg)
    assert '<b style="color:#b42318">\u26a0\ufe0f Tornado Watch</b>' in html
    assert "Tornado Watch until 9 PM" in html
    assert msg["Subject"].startswith("\u26a0\ufe0f ")


def test_info_banner_for_marginal_and_mentions():
    sev = Severity(outlooks=(outlook(1, "Marginal", 1),), mentions=("large hail",))
    msg = render([g()], {}, severity=sev)
    html = html_of(msg)
    assert 'class="bn-info"' in html and "background:#f3f6f9" in html
    assert "border:1px solid #dce3ea" in html
    assert "Heads up" in html and "\u26a0" not in html and 'bn-warn"' not in html
    assert "Marginal Risk (1/5) of severe storms," in html
    assert not msg["Subject"].startswith("\u26a0")
    assert "!! " not in msg.get_body(preferencelist=("plain",)).get_content()


def test_info_banner_for_mentions_only():
    html = html_of(render([g()], {}, severity=Severity(mentions=("blizzard",))))
    assert "Heads up" in html and "Graphics mention: blizzard" in html


def test_banner_day_label_today_vs_weekday():
    today = outlook(2, "Slight", 1, datetime(2026, 11, 6, 13, 0, tzinfo=UTC))
    sev = Severity(outlooks=(today, outlook()))
    html = html_of(render([g()], {}, severity=sev))
    assert "Slight Risk (2/5) of severe storms, today" in html
    assert "Enhanced Risk (3/5) of severe storms, Saturday" in html


def test_banner_text_escaped():
    sev = Severity(
        outlooks=(outlook(),),
        alerts=(Alert("Tornado <b>Watch</b>", "<script>x</script>"),),
        mentions=("<i>",),
    )
    for html in (html_of(render([g()], {}, severity=sev)), preview_of([g()], {}, severity=sev)):
        assert "<script>" not in html and "<i>" not in html
        assert "Tornado &lt;b&gt;Watch&lt;/b&gt;" in html
        assert "&lt;script&gt;x&lt;/script&gt;" in html


def test_flagged_preheader_and_plain_text():
    sev = Severity(outlooks=(outlook(),), alerts=(Alert("Tornado Watch", "Until 9 PM"),))
    msg = render([g(title="Alpha")], {}, severity=sev)
    html = html_of(msg)
    pre = html[html.index("opacity:0") :]
    assert pre.index("Enhanced Risk (3/5)") < pre.index("Alpha")
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    top = plain.split("\n\n")[0].splitlines()
    assert top[0] == "!! Enhanced Risk (3/5) of severe storms, Saturday"
    assert "!! Storm Prediction Center Day 2 outlook covers Edmond." in top
    assert "!! Tornado Watch" in top and "!! Until 9 PM" in top
    assert "Alpha" in plain.split("\n\n")[1]


def test_banner_dark_mode_classes_present():
    html = html_of(render([g()], {}, severity=Severity(outlooks=(outlook(),))))
    assert ".bn-warn{" in html and ".bn-info{" in html and ".bd-line{" in html


def test_preview_includes_banner_and_flag_state():
    sev = Severity(outlooks=(outlook(),))
    assert 'class="bn-warn"' in preview_of([g()], {}, severity=sev)
    assert "bn-" not in preview_of([g()], {}).replace(".bn-", "")


# --- Subject lead and note line ------------------------------------------------------------


def test_subject_lead_phrase_after_flag():
    got = format_subject("oun", NOW, "America/Chicago", flagged=True, lead="Tornado Warning")
    assert got == "⚠️ Tornado Warning · NWS OUN Graphicast — Fri Nov 6, 5:14 AM"
    got = format_subject("oun", NOW, "America/Chicago", lead="1 new graphic")
    assert got == "1 new graphic · NWS OUN Graphicast — Fri Nov 6, 5:14 AM"


def test_subject_lead_precedence():
    tz = "America/Chicago"
    enh = outlook(3, "Enhanced", 1, NOW)
    slgt = outlook(2, "Slight", 2)
    one = (Alert("Tornado Warning", "h"),)
    two = (*one, Alert("Flash Flood Watch", "h"))
    assert subject_lead(None, 0, NOW, tz) is None
    assert subject_lead(Severity(), 0, NOW, tz) is None
    assert subject_lead(Severity(), 1, NOW, tz) == "1 new graphic"
    assert subject_lead(Severity(), 3, NOW, tz) == "3 new graphics"
    assert subject_lead(Severity((slgt, enh), one), 2, NOW, tz) == "Tornado Warning"
    assert subject_lead(Severity((slgt, enh), two), 0, NOW, tz) == "Tornado Warning +1"
    assert subject_lead(Severity((slgt, enh)), 2, NOW, tz) == "Enhanced Risk today"
    assert subject_lead(Severity((slgt,)), 0, NOW, tz) == "Slight Risk Saturday"
    # Marginal alone is not flagged, so new graphics lead instead
    assert subject_lead(Severity((outlook(1, "Marginal"),)), 2, NOW, tz) == "2 new graphics"


def test_render_email_subject_uses_new_count_and_severity():
    msg = render([g(1), g(2, url="https://x/2.png")], {}, new_numbers=frozenset({2}))
    assert msg["Subject"].startswith("1 new graphic · NWS OUN Graphicast")
    sev = Severity(alerts=(Alert("Tornado Warning", "h"),))
    msg = render([g()], {}, severity=sev)
    assert msg["Subject"].startswith("⚠️ Tornado Warning · NWS OUN")


def test_note_in_html_and_plain_escaped():
    note = "Sent outside the usual schedule: new <b>Tornado</b> Warning."
    msg = render([g()], {}, note=note)
    html = html_of(msg)
    assert "new &lt;b&gt;Tornado&lt;/b&gt; Warning." in html
    assert "<b>Tornado</b>" not in html
    assert 'class="c-meta" style="padding:0 10px 10px;font-size:12px' in html
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert note in plain
    assert "new &lt;b&gt;Tornado&lt;/b&gt; Warning." in preview_of([g()], {}, note=note)


def test_no_note_means_no_note_row():
    assert "padding:0 10px 10px;font-size:12px" not in html_of(render([g()], {}))

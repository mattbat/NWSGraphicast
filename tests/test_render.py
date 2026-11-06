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
)

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
    assert "background:#f7fafb" in html
    assert "#0b1f3a" in html and "linear-gradient(135deg" in html
    assert "border-bottom:4px solid #f5a524" in html
    assert "NWS NORMAN &middot; GRAPHICAST" in html and "Forecast update" in html
    assert "Friday, November 6 \u00b7 5:14 AM" in html


def test_dark_mode_and_color_scheme_metas():
    html = html_of(render([g()], {}))
    assert "@media (prefers-color-scheme: dark)" in html
    for token in ("#0f1318", "#182029", "#26303c", "#e8eef6", "#c3cfdd", "#8b9bb0", "#8ab4ff"):
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
    assert html.index("New: Gamma") < html.index("Forecast update")


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


def test_graphic_count_singular_plural():
    assert "&middot;&nbsp; 1 graphic<" in html_of(render([g(1)], {}))
    three = [g(1), g(2, url="https://x/2.png"), g(3, url="https://x/3.png")]
    assert "&middot;&nbsp; 3 graphics<" in html_of(render(three, {}))


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

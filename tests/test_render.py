from __future__ import annotations

import email
from datetime import UTC, datetime
from email import policy

from graphicast.model import Graphic
from graphicast.render import (
    format_subject,
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
        graphics=graphics,
        images=images,
        now=NOW,
        tz="America/Chicago",
        sender="a@example.com",
        to="b@example.com",
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
    assert "https://www.weather.gov/oun" in text
    assert "https://www.spc.noaa.gov/" in text


def test_no_description_omits_paragraph():
    html = html_of(render([g(desc=None)], {}))
    assert '<p style="margin:4px' not in html


def test_html_escapes_feed_text():
    bad = g(title='<script>alert(1)</script> & "q"', desc="<b>x</b>")
    html = html_of(render([bad], {}))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "&quot;q&quot;" in html
    preview = render_html_preview(office="oun", graphics=[bad], images={})
    assert "<script>" not in preview


def test_unicode_text():
    msg = render([g(title="Café ☃ — 天気", desc="über")], {})
    assert "天気" in html_of(msg)
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert "☃" in parsed.get_body(preferencelist=("plain",)).get_content()


def test_footer_links():
    html = html_of(render([g()], {}))
    assert 'href="https://www.weather.gov/oun"' in html
    assert "NWS OUN" in html
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


def test_same_url_shared_cid():
    a, b = g(1), g(2)
    msg = render([a, b], {a.image_url: PNG})
    assert len([p for p in msg.walk() if p.get_content_maintype() == "image"]) == 1


def test_preview_data_uris():
    a, b = g(1), g(2, url="https://x/2.png")
    html = render_html_preview(office="oun", graphics=[a, b], images={a.image_url: PNG})
    assert "data:image/png;base64," in html
    assert 'src="https://x/2.png"' in html

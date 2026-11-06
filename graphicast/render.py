"""Render the graphicast email (plain text + HTML with hosted or inline CID images)."""

from __future__ import annotations

import base64
import email.utils
from collections.abc import Callable
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape
from zoneinfo import ZoneInfo

from graphicast.model import Graphic

SPC_URL = "https://www.spc.noaa.gov/"


def office_url(office: str) -> str:
    return f"https://www.weather.gov/{office.lower()}"


def image_type(data: bytes) -> tuple[str, str]:
    """(maintype, subtype) sniffed from magic bytes."""
    if data.startswith(b"\x89PNG"):
        return "image", "png"
    if data.startswith(b"GIF8"):
        return "image", "gif"
    if data.startswith(b"\xff\xd8"):
        return "image", "jpeg"
    return "application", "octet-stream"


def format_subject(office: str, now: datetime, tz: str) -> str:
    local = now.astimezone(ZoneInfo(tz))
    hour = str(int(local.strftime("%I")))
    return f"NWS {office.upper()} Graphicast — {local:%a %b} {local.day}, {hour}:{local:%M %p}"


def _render_plain(
    office: str, graphics: list[Graphic], hosted_urls: dict[str, str] | None = None
) -> str:
    blocks = []
    for g in graphics:
        lines = [g.title]
        if g.description:
            lines.append(g.description)
        if hosted_urls and g.image_url in hosted_urls:
            lines.append(hosted_urls[g.image_url])
        lines.append(f"Current version on weather.gov: {g.image_url}")
        blocks.append("\n".join(lines))
    footer = f"NWS {office.upper()}: {office_url(office)}\nStorm Prediction Center: {SPC_URL}"
    return "\n\n".join([*blocks, footer]) + "\n"


def _render_html(office: str, graphics: list[Graphic], src_for: Callable[[Graphic], str]) -> str:
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Arial,Helvetica,sans-serif;max-width:800px;margin:0 auto;'
        'padding:8px;color:#222">'
    ]
    for g in graphics:
        title = escape(g.title)
        parts.append(f'<h2 style="margin:16px 0 4px">{title}</h2>')
        if g.description:
            parts.append(f'<p style="margin:4px 0 8px">{escape(g.description)}</p>')
        parts.append(
            f'<img src="{escape(src_for(g), quote=True)}" alt="{escape(g.title, quote=True)}" '
            'width="100%" style="max-width:100%;height:auto">'
        )
        parts.append(
            '<p style="margin:2px 0 8px;font-size:12px">'
            f'<a href="{escape(g.image_url, quote=True)}">Current version on weather.gov</a></p>'
        )
    parts.append(
        '<p style="margin-top:24px;font-size:12px;color:#555">'
        f'<a href="{escape(office_url(office), quote=True)}">NWS {escape(office.upper())}</a>'
        f' | <a href="{SPC_URL}">Storm Prediction Center</a></p></body></html>'
    )
    return "\n".join(parts)


def render_email(
    *,
    office: str,
    graphics: list[Graphic],
    images: dict[str, bytes],
    now: datetime,
    tz: str,
    sender: str,
    to: str,
    hosted_urls: dict[str, str] | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = format_subject(office, now, tz)
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = email.utils.format_datetime(now)
    cids: dict[str, str] = {}
    for g in graphics:
        if hosted_urls is None and g.image_url in images and g.image_url not in cids:
            cids[g.image_url] = make_msgid()

    def src(g: Graphic) -> str:
        if hosted_urls and g.image_url in hosted_urls:
            return hosted_urls[g.image_url]
        cid = cids.get(g.image_url)
        return f"cid:{cid[1:-1]}" if cid else g.image_url

    msg.set_content(_render_plain(office, graphics, hosted_urls))
    msg.add_alternative(_render_html(office, graphics, src), subtype="html")
    html_part = msg.get_payload()[1]
    for url, cid in cids.items():
        maintype, subtype = image_type(images[url])
        html_part.add_related(images[url], maintype, subtype, cid=cid)
    return msg


def render_html_preview(*, office: str, graphics: list[Graphic], images: dict[str, bytes]) -> str:
    """HTML with downloaded images inlined as data: URIs."""

    def src(g: Graphic) -> str:
        data = images.get(g.image_url)
        if data is None:
            return g.image_url
        maintype, subtype = image_type(data)
        return f"data:{maintype}/{subtype};base64,{base64.b64encode(data).decode('ascii')}"

    return _render_html(office, graphics, src)

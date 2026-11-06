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


# Design tokens (docs/IMPLEMENTATION.md section 11.1). Light values are inline; dark values
# are applied by the classes in _STYLE under prefers-color-scheme: dark.
PAGE, CARD, LINE = "#f7fafb", "#ffffff", "#e4eaee"
NAVY, NAVY2, AMBER = "#0b1f3a", "#14325c", "#f5a524"
BODY, META, LINK = "#3b4654", "#7a8594", "#1d4f91"
SHADOW = "0 1px 2px rgba(16,24,40,.05),0 6px 16px rgba(16,24,40,.06)"
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"
PREHEADER_PAD = "&#8203;&nbsp;" * 60

_STYLE = (
    ":root{color-scheme:light dark;supported-color-schemes:light dark}"
    "@media (prefers-color-scheme: dark){"
    ".bg-page{background:#0f1318 !important}"
    ".bg-card{background:#182029 !important;border-color:#26303c !important}"
    ".c-title{color:#e8eef6 !important}"
    ".c-body{color:#c3cfdd !important}"
    ".c-meta{color:#8b9bb0 !important}"
    ".c-link{color:#8ab4ff !important}"
    ".badge{background:#3a2a0a !important;color:#fcd34d !important}"
    "}"
)


def _local(dt: datetime, tz: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz))


def _clock(local: datetime) -> str:
    return f"{int(local.strftime('%I'))}:{local:%M %p}"


def format_valid_until(end: datetime, tz: str) -> str:
    """e.g. "Fri 5:14 AM" in the local time zone."""
    local = _local(end, tz)
    return f"{local:%a} {_clock(local)}"


def _graphic_count(n: int) -> str:
    return f"{n} graphic" if n == 1 else f"{n} graphics"


def _preheader(graphics: list[Graphic], new_numbers: frozenset[int]) -> str:
    """Hidden inbox-preview text: titles joined by " · ", NEW ones first and prefixed."""
    new = [f"New: {g.title}" for g in graphics if g.number in new_numbers]
    old = [g.title for g in graphics if g.number not in new_numbers]
    return escape(" · ".join([*new, *old]))


def _footer_note(office_name: str, image_days: int | None) -> str:
    note = f"Sent when NWS {office_name} updates its graphics"
    return note + (f" \u00b7 images expire after {image_days} days" if image_days else "")


def _render_plain(
    office: str,
    office_name: str,
    graphics: list[Graphic],
    tz: str,
    hosted_urls: dict[str, str] | None,
    new_numbers: frozenset[int],
    image_days: int | None,
) -> str:
    blocks = []
    for g in graphics:
        lines = [f"[NEW] {g.title}" if g.number in new_numbers else g.title]
        lines.append(f"Valid until {format_valid_until(g.end, tz)}")
        if g.description:
            lines.append(g.description)
        if hosted_urls and g.image_url in hosted_urls:
            lines.append(hosted_urls[g.image_url])
        lines.append(f"View on weather.gov: {g.image_url}")
        blocks.append("\n".join(lines))
    footer = (
        f"NWS {office_name}: {office_url(office)}\nStorm Prediction Center: {SPC_URL}\n"
        + _footer_note(office_name, image_days)
    )
    return "\n\n".join([*blocks, footer]) + "\n"


def _card(g: Graphic, src: str, tz: str, is_new: bool) -> str:
    title = escape(g.title)
    badge = (
        '<span class="badge" style="display:inline-block;background:#fff4dc;color:#8a4b00;'
        "font-size:10px;font-weight:700;letter-spacing:.08em;padding:3px 8px;"
        'border-radius:999px;margin-left:8px;vertical-align:3px">NEW</span>'
        if is_new
        else ""
    )
    desc = (
        f'<p class="c-body" style="margin:0 0 16px;font-size:15px;line-height:1.55;'
        f'color:{BODY}">{escape(g.description)}</p>'
        if g.description
        else ""
    )
    alt = escape(f"{g.title} (image unavailable, see weather.gov link below)", quote=True)
    url = escape(g.image_url, quote=True)
    return f"""<tr><td style="padding:0 0 18px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg-card" style="background:{CARD};border:1px solid {LINE};border-radius:16px;box-shadow:{SHADOW}">
<tr><td style="padding:20px 20px 0">
<div class="c-title" style="font-size:19px;font-weight:700;letter-spacing:-.01em;color:{NAVY}">{title}{badge}</div>
<div class="c-meta" style="font-size:12px;color:{META};margin:6px 0 12px"><span style="color:{AMBER}">&#9679;</span>&nbsp; Valid until {format_valid_until(g.end, tz)}</div>
{desc}</td></tr>
<tr><td style="padding:0 12px"><img src="{escape(src, quote=True)}" alt="{alt}" width="100%" style="display:block;width:100%;height:auto;border:0;border-radius:10px;font-size:13px;color:{META}"></td></tr>
<tr><td style="padding:12px 20px 18px;font-size:13px;font-weight:600"><a class="c-link" href="{url}" style="color:{LINK};text-decoration:none">View on weather.gov&nbsp;&rarr;</a></td></tr>
</table></td></tr>"""


def _render_html(
    office: str,
    office_name: str,
    graphics: list[Graphic],
    src_for: Callable[[Graphic], str],
    now: datetime,
    tz: str,
    new_numbers: frozenset[int],
    image_days: int | None,
) -> str:
    local = _local(now, tz)
    stamp = f"{local:%A, %B} {local.day} \u00b7 {_clock(local)}"
    name = escape(office_name)
    cards = "\n".join(_card(g, src_for(g), tz, g.number in new_numbers) for g in graphics)
    note = escape(_footer_note(office_name, image_days))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>NWS {name} Graphicast</title>
<style>{_STYLE}</style></head>
<body class="bg-page" style="margin:0;padding:0;background:{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_preheader(graphics, new_numbers)}{PREHEADER_PAD}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg-page" style="background:{PAGE};font-family:{FONT}">
<tr><td align="center" style="padding:14px 12px 8px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px">
<tr><td style="padding:0 0 18px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NAVY};background-image:linear-gradient(135deg,{NAVY} 0%,{NAVY2} 100%);border-radius:16px;overflow:hidden;box-shadow:{SHADOW}">
<tr><td style="padding:22px 22px 20px;border-bottom:4px solid {AMBER}">
<div style="font-size:11px;font-weight:700;letter-spacing:.14em;color:{AMBER}">NWS {escape(office_name.upper())} &middot; GRAPHICAST</div>
<div style="font-size:26px;font-weight:800;letter-spacing:-.02em;color:#ffffff;margin-top:6px">Forecast update</div>
<div style="font-size:13px;color:#b9c6d8;margin-top:4px">{stamp} &nbsp;&middot;&nbsp; {_graphic_count(len(graphics))}</div>
</td></tr>
</table></td></tr>
{cards}
<tr><td class="c-meta" style="padding:6px 8px 26px;text-align:center;font-size:12px;line-height:1.7;color:#8a94a3">
<a class="c-link" href="{escape(office_url(office), quote=True)}" style="color:{LINK};text-decoration:none;font-weight:600">NWS {name}</a> &nbsp;&middot;&nbsp;
<a class="c-link" href="{SPC_URL}" style="color:{LINK};text-decoration:none;font-weight:600">Storm Prediction Center</a><br>
{note}</td></tr>
</table></td></tr></table>
</body></html>
"""


def render_email(
    *,
    office: str,
    office_name: str,
    graphics: list[Graphic],
    images: dict[str, bytes],
    now: datetime,
    tz: str,
    sender: str,
    to: str,
    hosted_urls: dict[str, str] | None = None,
    new_numbers: frozenset[int] = frozenset(),
    image_days: int | None = None,
) -> EmailMessage:
    """Build the multipart email. `image_days` is shown in the footer (hosted mode only)."""
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

    msg.set_content(
        _render_plain(office, office_name, graphics, tz, hosted_urls, new_numbers, image_days)
    )
    html = _render_html(office, office_name, graphics, src, now, tz, new_numbers, image_days)
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[1]
    for url, cid in cids.items():
        maintype, subtype = image_type(images[url])
        html_part.add_related(images[url], maintype, subtype, cid=cid)
    return msg


def render_html_preview(
    *,
    office: str,
    office_name: str,
    graphics: list[Graphic],
    images: dict[str, bytes],
    now: datetime,
    tz: str,
    new_numbers: frozenset[int] = frozenset(),
    image_days: int | None = None,
) -> str:
    """HTML with downloaded images inlined as data: URIs."""

    def src(g: Graphic) -> str:
        data = images.get(g.image_url)
        if data is None:
            return g.image_url
        maintype, subtype = image_type(data)
        return f"data:{maintype}/{subtype};base64,{base64.b64encode(data).decode('ascii')}"

    return _render_html(office, office_name, graphics, src, now, tz, new_numbers, image_days)

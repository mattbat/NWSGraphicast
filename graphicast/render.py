"""Render the graphicast email (plain text + HTML with hosted or inline CID images)."""

from __future__ import annotations

import base64
import email.utils
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape
from zoneinfo import ZoneInfo

from graphicast.model import Graphic
from graphicast.severity import Severity

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


def format_subject(office: str, now: datetime, tz: str, flagged: bool = False) -> str:
    local = now.astimezone(ZoneInfo(tz))
    hour = str(int(local.strftime("%I")))
    flag = "\u26a0\ufe0f " if flagged else ""
    return (
        f"{flag}NWS {office.upper()} Graphicast — {local:%a %b} {local.day}, {hour}:{local:%M %p}"
    )


# Design tokens (docs/IMPLEMENTATION.md sections 11.1 and 12.1). Light values are inline; dark
# values are applied by the classes in _STYLE under prefers-color-scheme: dark.
PAGE, LINE = "#ffffff", "#e4eaee"
NAVY, AMBER = "#0b1f3a", "#f5a524"
BODY, META, LINK = "#3b4654", "#7a8594", "#1d4f91"
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"
PREHEADER_PAD = "&#8203;&nbsp;" * 60

_STYLE = (
    ":root{color-scheme:light dark;supported-color-schemes:light dark}"
    "@media (prefers-color-scheme: dark){"
    ".bg-page{background:#0f1318 !important}"
    ".bd-line{border-color:#26303c !important}"
    ".c-title{color:#e8eef6 !important}"
    ".c-body{color:#c3cfdd !important}"
    ".c-meta{color:#8b9bb0 !important}"
    ".c-link{color:#8ab4ff !important}"
    ".badge{background:#3a2a0a !important;color:#fcd34d !important}"
    ".bn-warn{background:#2b1d0e !important;border-color:#6b4a1c !important;color:#f3c27a !important}"
    ".bn-warn b{color:#ff9b8f !important}"
    ".bn-info{background:#182029 !important;border-color:#26303c !important;color:#c3cfdd !important}"
    ".bn-info b{color:#e8eef6 !important}"
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


@dataclass(frozen=True)
class Banner:
    """The severe-weather / heads-up banner: a title, then (bold text, detail) entries."""

    flagged: bool
    title: str
    entries: tuple[tuple[str, str], ...]

    def plain_lines(self) -> list[str]:
        """Every non-empty bold/detail line, prefixed `!! ` when flagged."""
        prefix = "!! " if self.flagged else ""
        return [prefix + t for entry in self.entries for t in entry if t]


def _day_label(valid: datetime, now: datetime, tz: str) -> str:
    local = _local(valid, tz)
    return "today" if local.date() == _local(now, tz).date() else f"{local:%A}"


def build_banner(
    severity: Severity | None, place_name: str, now: datetime, tz: str
) -> Banner | None:
    """Banner content (section 12.5), or None when there is nothing to show."""
    if severity is None:
        return None
    entries: list[tuple[str, str]] = []
    for o in severity.outlooks:
        label = _day_label(o.valid, now, tz)
        entries.append(
            (
                f"{o.name} Risk ({o.level}/5) of severe storms, {label}",
                f"Storm Prediction Center Day {o.day} outlook covers {place_name}.",
            )
        )
    entries.extend((a.event, a.headline) for a in severity.alerts)
    if severity.mentions:
        entries.append(("", "Graphics mention: " + ", ".join(severity.mentions)))
    if not entries:
        return None
    title = "" if severity.flagged else "Heads up"
    return Banner(severity.flagged, title, tuple(entries))


def _banner_html(banner: Banner) -> str:
    """The banner cell, joined to the header bar above it."""
    cls, bg, border, color, title_color = (
        ("bn-warn", "#fff4e5", "#f3c27a", "#7a3d00", "#b42318")
        if banner.flagged
        else ("bn-info", "#f3f6f9", "#dce3ea", BODY, NAVY)
    )
    lines = []
    if banner.title:
        lines.append(f'<b style="color:{title_color}">{escape(banner.title)}</b>')
    for i, (strong, detail) in enumerate(banner.entries):
        if strong:
            icon = "\u26a0\ufe0f " if banner.flagged and i == 0 else ""
            lines.append(f'<b style="color:{title_color}">{icon}{escape(strong)}</b>')
        if detail:
            lines.append(f'<span style="font-size:12px">{escape(detail)}</span>')
    return (
        f'<tr><td class="{cls}" style="background:{bg};border:1px solid {border};border-top:0;'
        "border-radius:0 0 12px 12px;padding:10px 14px;font-size:13px;line-height:1.45;"
        f'color:{color}">' + "<br>".join(lines) + "</td></tr>"
    )


def _header_html(office_name: str, stamp: str, banner: Banner | None) -> str:
    radius = "12px 12px 0 0" if banner else "12px"
    border = "" if banner else f"border-bottom:3px solid {AMBER};"
    bar = (
        f'<tr><td style="background:{NAVY};{border}border-radius:{radius};padding:11px 14px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="font-size:11px;font-weight:700;letter-spacing:.12em;color:{AMBER}">NWS {escape(office_name.upper())} &middot; GRAPHICAST</td>'
        f'<td align="right" style="font-size:12px;color:#c9d4e3;white-space:nowrap">{escape(stamp)}</td>'
        "</tr></table></td></tr>"
    )
    inner = bar + (_banner_html(banner) if banner else "")
    return (
        '<tr><td style="padding:0 8px"><table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0">{inner}</table></td></tr>'
        '<tr><td style="height:10px;font-size:0;line-height:0">&nbsp;</td></tr>'
    )


def _preheader(
    graphics: list[Graphic], new_numbers: frozenset[int], banner: Banner | None = None
) -> str:
    """Hidden inbox-preview text: titles joined by " · ", NEW ones first and prefixed.
    A flagged banner's first line leads."""
    new = [f"New: {g.title}" for g in graphics if g.number in new_numbers]
    old = [g.title for g in graphics if g.number not in new_numbers]
    lead = [banner.entries[0][0] or banner.entries[0][1]] if banner and banner.flagged else []
    return escape(" · ".join([*lead, *new, *old]))


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
    banner: Banner | None,
) -> str:
    blocks = ["\n".join(banner.plain_lines())] if banner else []
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


def _graphic_block(g: Graphic, src: str, tz: str, is_new: bool) -> str:
    """Layout B: text block, full-width image, link row with a divider, spacer."""
    title = escape(g.title)
    badge = (
        '<span class="badge" style="display:inline-block;background:#fff4dc;color:#8a4b00;'
        "font-size:10px;font-weight:700;letter-spacing:.08em;padding:3px 8px;"
        'border-radius:999px;margin-left:8px;vertical-align:3px">NEW</span>'
        if is_new
        else ""
    )
    desc = (
        f'<p class="c-body" style="margin:6px 0 0;font-size:15px;line-height:1.5;'
        f'color:{BODY}">{escape(g.description)}</p>'
        if g.description
        else ""
    )
    alt = escape(f"{g.title} (image unavailable, see weather.gov link below)", quote=True)
    url = escape(g.image_url, quote=True)
    return f"""<tr><td style="padding:4px 10px 10px">
<div class="c-title" style="font-size:18px;font-weight:700;color:{NAVY}">{title}{badge}</div>
<div class="c-meta" style="font-size:12px;color:{META};margin-top:4px"><span style="color:{AMBER}">&#9679;</span>&nbsp; Valid until {format_valid_until(g.end, tz)}</div>{desc}</td></tr>
<tr><td style="padding:0"><img src="{escape(src, quote=True)}" alt="{alt}" width="100%" style="display:block;width:100%;height:auto;border:0;font-size:13px;color:{META}"></td></tr>
<tr><td class="bd-line" style="padding:8px 10px 22px;border-bottom:1px solid {LINE}"><a class="c-link" href="{url}" style="color:{LINK};text-decoration:none;font-weight:600;font-size:13px">View on weather.gov&nbsp;&rarr;</a></td></tr>
<tr><td style="height:14px;font-size:0;line-height:0">&nbsp;</td></tr>"""


def _render_html(
    office: str,
    office_name: str,
    graphics: list[Graphic],
    src_for: Callable[[Graphic], str],
    now: datetime,
    tz: str,
    new_numbers: frozenset[int],
    image_days: int | None,
    banner: Banner | None,
) -> str:
    local = _local(now, tz)
    stamp = f"{local:%a %b} {local.day} \u00b7 {_clock(local)}"
    name = escape(office_name)
    blocks = "\n".join(_graphic_block(g, src_for(g), tz, g.number in new_numbers) for g in graphics)
    note = escape(_footer_note(office_name, image_days))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>NWS {name} Graphicast</title>
<style>{_STYLE}</style></head>
<body class="bg-page" style="margin:0;padding:0;background:{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_preheader(graphics, new_numbers, banner)}{PREHEADER_PAD}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg-page" style="background:{PAGE};font-family:{FONT}">
<tr><td align="center" style="padding:8px 0 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px">
{_header_html(office_name, stamp, banner)}
{blocks}
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
    severity: Severity | None = None,
    place_name: str = "Edmond",
) -> EmailMessage:
    """Build the multipart email. `image_days` is shown in the footer (hosted mode only)."""
    msg = EmailMessage()
    banner = build_banner(severity, place_name, now, tz)
    msg["Subject"] = format_subject(office, now, tz, flagged=bool(severity and severity.flagged))
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
        _render_plain(
            office, office_name, graphics, tz, hosted_urls, new_numbers, image_days, banner
        )
    )
    html = _render_html(
        office, office_name, graphics, src, now, tz, new_numbers, image_days, banner
    )
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
    severity: Severity | None = None,
    place_name: str = "Edmond",
) -> str:
    """HTML with downloaded images inlined as data: URIs."""

    def src(g: Graphic) -> str:
        data = images.get(g.image_url)
        if data is None:
            return g.image_url
        maintype, subtype = image_type(data)
        return f"data:{maintype}/{subtype};base64,{base64.b64encode(data).decode('ascii')}"

    banner = build_banner(severity, place_name, now, tz)
    return _render_html(
        office, office_name, graphics, src, now, tz, new_numbers, image_days, banner
    )

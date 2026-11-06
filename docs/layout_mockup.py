"""Design reference for layout B and the severe banner (IMPLEMENTATION.md section 12).

Not imported by the package. Run from the repo root: python docs/layout_mockup.py
"""

import sys
from datetime import UTC, datetime
from html import escape as e
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graphicast.model import active_graphics
from graphicast.sources import fetch_graphics

TZ = ZoneInfo("America/Chicago")
now = datetime.now(UTC)
_, gs = fetch_graphics("oun")
gs = active_graphics(gs, now)
local = now.astimezone(TZ)


def t(dt):
    d = dt.astimezone(TZ)
    return f"{d:%a} {int(d.strftime('%I'))}:{d:%M %p}"


STAMP = f"{local:%a %b} {local.day} · {int(local.strftime('%I'))}:{local:%M %p}"
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"
NAVY, AMBER, PAGE, LINE = "#0b1f3a", "#f5a524", "#f7fafb", "#e4eaee"


def header(severe=None):
    bar = f"""<tr><td style="background:{NAVY};border-bottom:3px solid {AMBER};border-radius:12px;padding:11px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:11px;font-weight:700;letter-spacing:.12em;color:{AMBER}">NWS NORMAN · GRAPHICAST</td>
<td align="right" style="font-size:12px;color:#c9d4e3">{STAMP}</td></tr></table></td></tr>"""
    if severe:
        level, text = severe
        bar = bar.replace("border-radius:12px", "border-radius:12px 12px 0 0").replace(
            f"border-bottom:3px solid {AMBER};", ""
        )
        bar += f"""<tr><td style="background:#fff4e5;border:1px solid #f3c27a;border-top:0;border-radius:0 0 12px 12px;padding:10px 14px;font-size:13px;line-height:1.45;color:#7a3d00">
<b style="color:#b42318">⚠️ {e(level)}</b><br>{e(text)}</td></tr>"""
    return bar + '<tr><td style="height:10px;font-size:0">&nbsp;</td></tr>'


def text_block(g):
    d = (
        f'<p style="margin:6px 0 0;font-size:15px;line-height:1.5;color:#3b4654">{e(g.description)}</p>'
        if g.description
        else ""
    )
    return (
        f'<div style="font-size:18px;font-weight:700;color:{NAVY}">{e(g.title)}</div>'
        f'<div style="font-size:12px;color:#7a8594;margin-top:4px"><span style="color:{AMBER}">●</span>&nbsp; Valid until {t(g.end)}</div>{d}'
    )


def link(g):
    return f'<a href="{g.image_url}" style="color:#1d4f91;text-decoration:none;font-weight:600;font-size:13px">View on weather.gov&nbsp;→</a>'


def bleed_cards(severe=None):
    rows = ""
    for g in gs:
        rows += f"""<tr><td style="padding:0 0 12px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="background:#fff;border:1px solid {LINE};border-radius:14px;overflow:hidden">
<tr><td style="padding:14px 14px 12px">{text_block(g)}</td></tr>
<tr><td style="padding:0"><img src="{g.image_url}" width="100%" style="display:block;width:100%;height:auto;border:0"></td></tr>
<tr><td style="padding:10px 14px 12px">{link(g)}</td></tr></table></td></tr>"""
    return wrap(header(severe) + rows, pad="8px 6px")


def no_cards(severe=None):
    rows = ""
    for g in gs:
        rows += f"""<tr><td style="padding:4px 10px 10px">{text_block(g)}</td></tr>
<tr><td style="padding:0"><img src="{g.image_url}" width="100%" style="display:block;width:100%;height:auto;border:0"></td></tr>
<tr><td style="padding:8px 10px 22px;border-bottom:1px solid {LINE}">{link(g)}</td></tr><tr><td style="height:14px"></td></tr>"""
    return wrap(header(severe) + rows, pad="8px 0", bg="#ffffff", hpad="0 8px")


def wrap(inner, pad, bg=PAGE, hpad="0"):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:{bg}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{bg};font-family:{FONT}">
<tr><td align="center" style="padding:{pad}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px">
{inner}</table></td></tr></table></body></html>"""


SEV = (
    "Enhanced Risk (3/5) of severe storms, Saturday",
    "Storm Prediction Center Day 2 outlook covers Norman. Tornadoes and large hail possible.",
)
Path("L1_bleed.html").write_text(bleed_cards())
Path("L2_nocards.html").write_text(no_cards().replace(">NWS NORMAN", ">NWS NORMAN", 1))
Path("L3_bleed_severe.html").write_text(bleed_cards(SEV))
print("ok")

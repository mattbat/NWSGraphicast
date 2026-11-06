"""Design reference for the email (section 11 of IMPLEMENTATION.md). Not imported by the package.

Render: python docs/email_mockup.py (writes p_*.html into the current directory).
"""
import sys
from datetime import UTC, datetime
from html import escape as e
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, "/home/user/NWSGraphicast")
from graphicast.model import active_graphics
from graphicast.sources import fetch_graphics

TZ = ZoneInfo("America/Chicago")
now = datetime.now(UTC)
_, gs = fetch_graphics("oun")
gs = active_graphics(gs, now)
NEW = {gs[1].number}
local = now.astimezone(TZ)
def t(dt):
    d = dt.astimezone(TZ); return f"{d:%a} {int(d.strftime('%I'))}:{d:%M %p}"
stamp = f"{local:%A, %B} {local.day} · {int(local.strftime('%I'))}:{local:%M %p}"
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"

BGS = {
  "1_matched": ("#f7fafb", "#e4eaee"),   # sampled from the user's mail app
  "2_gray":    ("#f2f4f6", "#e1e5ea"),
  "3_sage":    ("#f1f5f2", "#dfe7e1"),
  "4_mist":    ("#eff4f9", "#dce5ef"),
}
NAVY, NAVY2, AMBER = "#0b1f3a", "#14325c", "#f5a524"
SHADOW = "0 1px 2px rgba(16,24,40,.05),0 6px 16px rgba(16,24,40,.06)"

def email(bg, line):
    cards = ""
    for g in gs:
        badge = ('<span style="display:inline-block;background:#fff4dc;color:#8a4b00;font-size:10px;font-weight:700;'
                 'letter-spacing:.08em;padding:3px 8px;border-radius:999px;margin-left:8px;vertical-align:3px">NEW</span>'
                 if g.number in NEW else "")
        desc = (f'<p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#3b4654">{e(g.description)}</p>'
                if g.description else "")
        cards += f"""<tr><td style="padding:0 0 18px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid {line};border-radius:16px;box-shadow:{SHADOW}">
<tr><td style="padding:20px 20px 0">
<div style="font-size:19px;font-weight:700;letter-spacing:-.01em;color:{NAVY}">{e(g.title)}{badge}</div>
<div style="font-size:12px;color:#7a8594;margin:6px 0 12px"><span style="color:{AMBER}">●</span>&nbsp; Valid until {t(g.end)}</div>
{desc}</td></tr>
<tr><td style="padding:0 12px"><img src="{g.image_url}" alt="{e(g.title)}" width="100%" style="display:block;width:100%;height:auto;border:0;border-radius:10px"></td></tr>
<tr><td style="padding:12px 20px 18px;font-size:13px;font-weight:600"><a href="{g.image_url}" style="color:#1d4f91;text-decoration:none">View on weather.gov&nbsp;→</a></td></tr>
</table></td></tr>"""
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{bg};font-family:{FONT}">
<tr><td align="center" style="padding:14px 12px 8px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px">
<tr><td style="padding:0 0 18px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NAVY};background-image:linear-gradient(135deg,{NAVY} 0%,{NAVY2} 100%);border-radius:16px;overflow:hidden;box-shadow:{SHADOW}">
<tr><td style="padding:22px 22px 20px;border-bottom:4px solid {AMBER}">
<div style="font-size:11px;font-weight:700;letter-spacing:.14em;color:{AMBER}">NWS NORMAN · GRAPHICAST</div>
<div style="font-size:26px;font-weight:800;letter-spacing:-.02em;color:#ffffff;margin-top:6px">Forecast update</div>
<div style="font-size:13px;color:#b9c6d8;margin-top:4px">{stamp} &nbsp;·&nbsp; {len(gs)} graphics</div>
</td></tr>
</table></td></tr>
{cards}
<tr><td style="padding:6px 8px 26px;text-align:center;font-size:12px;line-height:1.7;color:#8a94a3">
<a href="https://www.weather.gov/oun" style="color:#1d4f91;text-decoration:none;font-weight:600">NWS Norman</a> &nbsp;·&nbsp;
<a href="https://www.spc.noaa.gov/" style="color:#1d4f91;text-decoration:none;font-weight:600">Storm Prediction Center</a><br>
Sent when NWS Norman updates its graphics · images expire after 7 days</td></tr>
</table></td></tr></table>"""

def app_frame(inner):
    """Mimic the user's mail app: #f7fafb chrome, subject, white rounded sheet."""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f7fafb;font-family:{FONT}">
<div style="padding:18px 16px 14px;font-size:22px;font-weight:800;color:#111">NWS OUN Graphicast — Fri Nov 6, 7:09 AM</div>
<div style="background:#fff;border-radius:22px 22px 0 0;padding:16px 0 0">
<div style="padding:0 20px 12px;display:flex;justify-content:space-between"><div><div style="font-size:16px;font-weight:600">Batchelderbot</div>
<div style="font-size:14px;color:#3b82f6">To: Mrmacman</div></div><div style="color:#888;font-size:14px">7:09 AM</div></div>
{inner}</div></body></html>"""

for name, (bg, line) in BGS.items():
    Path(f"p_{name}.html").write_text(app_frame(email(bg, line)))
print("ok")

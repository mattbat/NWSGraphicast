"""Design reference for the weather widget (IMPLEMENTATION.md section 14), accent style.

Not imported by the package and not runnable on its own (it needed a scratch helper for live
data). The `widget()` function is the approved markup; `lucide()` is the approved icon mapping.
"""

from html import escape as e
from pathlib import Path
import widget as w

FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def lucide(text, day=True):
    s = text.lower().split(" then ")[0]
    for k, v in (
        ("thunder", "cloud-lightning"),
        ("snow", "cloud-snow"),
        ("sleet", "cloud-snow"),
        ("flurr", "cloud-snow"),
        ("freezing", "cloud-hail"),
        ("ice", "cloud-hail"),
        ("drizzle", "cloud-drizzle"),
        ("rain", "cloud-rain"),
        ("shower", "cloud-rain"),
        ("fog", "cloud-fog"),
        ("haze", "cloud-fog"),
        ("smoke", "cloud-fog"),
        ("mist", "cloud-fog"),
        ("mostly cloudy", "cloudy"),
        ("overcast", "cloudy"),
        ("cloudy", "cloudy"),
        ("partly", "cloud-sun" if day else "cloud-moon"),
        ("mostly sunny", "cloud-sun"),
        ("mostly clear", "cloud-moon"),
        ("sunny", "sun"),
        ("clear", "sun" if day else "moon"),
        ("wind", "wind"),
    ):
        if k in s:
            return v
    return "thermometer"


def img(name, style, px):
    return f'<img src="icons_png/{name}_{style}.png" width="{px}" height="{px}" alt="" style="display:inline-block;vertical-align:middle;border:0">'


def widget(style, d):
    c1, c2 = w.gradient(d["cond"], d["day"])
    hours = ""
    any_pop = any(h[4] >= 20 for h in d["hours"])
    for lab, cond, day, temp, pop in d["hours"]:
        p = (
            (
                f'<div style="font-size:10px;font-weight:600;color:#a9dcff;line-height:11px">{pop}%</div>'
                if pop >= 20
                else '<div style="font-size:10px;line-height:11px">&nbsp;</div>'
            )
            if any_pop
            else ""
        )
        hours += (
            f'<td align="center" width="16%" style="padding:0">'
            f'<div style="font-size:11px;font-weight:500;color:rgba(255,255,255,.72);line-height:13px">{lab}</div>'
            f'<div style="padding:3px 0 1px;line-height:18px">{img(lucide(cond, day), style, 18)}</div>{p}'
            f'<div style="font-size:14px;font-weight:600;line-height:17px">{temp}°</div></td>'
        )
    stat = lambda icon, val: (
        f'<td align="center" width="25%" style="font-size:12px;font-weight:500;color:rgba(255,255,255,.9);white-space:nowrap">'
        f"{img(icon, style, 14)}&nbsp;{e(val)}</td>"
    )
    rule = '<tr><td style="padding:0 14px"><div style="height:1px;line-height:1px;font-size:0;background:rgba(255,255,255,.2)">&nbsp;</div></td></tr>'
    return f"""<tr><td style="padding:0 8px 12px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="background:{c1};background-image:linear-gradient(165deg,{c1} 0%,{c2} 100%);border-radius:16px;color:#fff;font-family:{FONT}">
<tr><td style="padding:9px 14px 7px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
 <td valign="middle" style="width:1%;white-space:nowrap;font-size:34px;font-weight:300;line-height:36px;letter-spacing:-1.5px;padding-right:10px">{d["temp"]}°</td>
 <td valign="middle"><div style="font-size:15px;font-weight:600;line-height:19px">{img(lucide(d["cond"], d["day"]), style, 18)}&nbsp;{e(d["cond"])}</div>
  <div style="font-size:12px;color:rgba(255,255,255,.75);line-height:16px">Feels like {d["feels"]}°</div></td>
 <td valign="middle" align="right"><div style="font-size:13px;font-weight:600;line-height:17px">Edmond&nbsp;{img("navigation", "mono", 10)}</div>
  <div style="font-size:13px;color:rgba(255,255,255,.85);line-height:17px">{d["hl"]}</div></td></tr></table></td></tr>
{rule}
<tr><td style="padding:6px 8px 6px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{hours}</tr></table></td></tr>
<tr><td style="padding:0 6px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
{stat("sunrise", d["rise"])}{stat("sunset", d["set"])}{stat("wind", d["wind"])}{stat("droplet", d["pop"])}</tr></table></td></tr>
</table></td></tr>"""


from datetime import datetime

live_hours = []
for i, h in enumerate(w.hourly[:6]):
    t = datetime.fromisoformat(h["startTime"])
    live_hours.append(
        (
            "Now" if i == 0 else f"{int(t.strftime('%I'))}{t.strftime('%p')}",
            h["shortForecast"],
            h["isDaytime"],
            w.cur_f if i == 0 else h["temperature"],
            h["probabilityOfPrecipitation"]["value"] or 0,
        )
    )
live = dict(
    temp=w.cur_f,
    cond=w.cur_text,
    day=w.is_day,
    feels=w.feels,
    hl=w.hl.replace(" L:", "&nbsp; L:"),
    hours=live_hours,
    rise=w.fmt(w.rise),
    set=w.fmt(w.sset),
    wind=w.wind.replace(" mph", ""),
    pop=f"{w.pop}%",
)
storm = dict(
    temp=78,
    cond="Thunderstorms",
    day=True,
    feels=81,
    hl="H:84°&nbsp; L:61°",
    hours=[
        ("Now", "Thunderstorms", True, 78, 70),
        ("3PM", "Showers and Thunderstorms", True, 74, 80),
        ("4PM", "Rain", True, 70, 60),
        ("5PM", "Partly Sunny", True, 72, 20),
        ("6PM", "Mostly Sunny", True, 71, 10),
        ("7PM", "Mostly Clear", False, 68, 0),
    ],
    rise="6:41 AM",
    set="8:31 PM",
    wind="SSW 18",
    pop="80%",
)
src = Path("L2_nocards.html").read_text()
marker = '<tr><td style="height:10px;font-size:0">&nbsp;</td></tr>'
for name, style, d in (
    ("P_mono_live", "mono", live),
    ("P_accent_live", "accent", live),
    ("P_mono_storm", "mono", storm),
    ("P_accent_storm", "accent", storm),
):
    Path(f"{name}.html").write_text(src.replace(marker, marker + widget(style, d), 1))
print("ok")

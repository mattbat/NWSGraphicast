"""The weather widget: HTML (docs/widget_mockup.py `widget`, accent icons) and a plain-text line.

The widget keeps its own gradient and white text and carries no dark-mode classes, so the
email's dark CSS never recolours it. Icons are decorative (`alt=""`)."""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path

from graphicast.weather import Conditions

ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif"
RAIN_MIN = 20  # show per-hour rain chances only when some hour reaches this percent
WET = ("thunder", "rain", "shower", "drizzle", "snow", "sleet")
GREY = ("fog", "cloudy", "overcast", "haze")


def icon_path(name: str) -> Path:
    """The icon file. Falls back to ./assets/icons when the package is installed elsewhere
    (the workflows run from a checkout but `pip install .` copies only the package)."""
    path = ICONS_DIR / f"{name}.png"
    return path if path.exists() else Path.cwd() / "assets" / "icons" / f"{name}.png"


def gradient(text: str, day: bool) -> tuple[str, str]:
    """(top-left, bottom-right) background colours for the conditions text."""
    s = text.lower()
    if any(k in s for k in WET):
        return "#3d4b5f", "#5f7189"
    if any(k in s for k in GREY):
        return "#5d7590", ("#8fa6be" if day else "#2b3a52")
    return ("#2f7fd8", "#69b2f0") if day else ("#0e1a3a", "#2b3d6b")


def icon_names(c: Conditions) -> list[str]:
    """Distinct icon names the widget uses, in first-use order."""
    names = [c.icon, "navigation", *(h.icon for h in c.hours)]
    names += ["sunrise", "sunset", "wind", "droplet"]
    return list(dict.fromkeys(names))


def clock(dt) -> str:
    return f"{int(dt.strftime('%I'))}:{dt:%M %p}"


def _wind_text(c: Conditions) -> str:
    return c.wind if c.wind == "Calm" else f"{c.wind} mph"


def widget_plain(c: Conditions) -> str:
    """One line, e.g. "Edmond 45° Fog (feels 38°) · H:55° L:40° · Sunrise 6:56 AM · ..."."""
    feels = f" (feels {c.feels}°)" if c.feels is not None else ""
    hi_lo = " ".join(c.hi_lo.split())
    return (
        f"{c.place} {c.temp}° {c.text}{feels} · {hi_lo} · Sunrise {clock(c.sunrise)} · "
        f"Sunset {clock(c.sunset)} · Wind {_wind_text(c)} · Rain {c.pop}%"
    )


def widget_html(c: Conditions, icon_src: Callable[[str], str]) -> str:
    """The widget's table rows, ready to place inside the email's content table."""

    def img(name: str, px: int) -> str:
        return (
            f'<img src="{escape(icon_src(name), quote=True)}" width="{px}" height="{px}" alt="" '
            'style="display:inline-block;vertical-align:middle;border:0">'
        )

    c1, c2 = gradient(c.text, c.is_day)
    any_pop = any(h.pop >= RAIN_MIN for h in c.hours)
    hours = ""
    for h in c.hours:
        if not any_pop:
            rain = ""
        elif h.pop >= RAIN_MIN:
            rain = f'<div style="font-size:10px;font-weight:600;color:#a9dcff;line-height:11px">{h.pop}%</div>'
        else:
            rain = '<div style="font-size:10px;line-height:11px">&nbsp;</div>'
        hours += (
            '<td align="center" width="16%" style="padding:0">'
            f'<div style="font-size:11px;font-weight:500;color:rgba(255,255,255,.72);line-height:13px">{escape(h.label)}</div>'
            f'<div style="padding:3px 0 1px;line-height:18px">{img(h.icon, 18)}</div>{rain}'
            f'<div style="font-size:14px;font-weight:600;line-height:17px">{h.temp}°</div></td>'
        )

    def stat(icon: str, value: str) -> str:
        return (
            '<td align="center" width="25%" style="font-size:12px;font-weight:500;color:rgba(255,255,255,.9);white-space:nowrap">'
            f"{img(icon, 14)}&nbsp;{escape(value)}</td>"
        )

    feels = (
        f'<div style="font-size:12px;color:rgba(255,255,255,.75);line-height:16px">Feels like {c.feels}°</div>'
        if c.feels is not None
        else ""
    )
    hi_lo = escape(c.hi_lo).replace("  ", "&nbsp; ")
    rule = '<tr><td style="padding:0 14px"><div style="height:1px;line-height:1px;font-size:0;background:rgba(255,255,255,.2)">&nbsp;</div></td></tr>'
    return f"""<tr><td style="padding:0 8px 12px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="background:{c1};background-image:linear-gradient(165deg,{c1} 0%,{c2} 100%);border-radius:16px;color:#fff;font-family:{FONT}">
<tr><td style="padding:9px 14px 7px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
 <td valign="middle" style="width:1%;white-space:nowrap;font-size:34px;font-weight:300;line-height:36px;letter-spacing:-1.5px;padding-right:10px">{c.temp}°</td>
 <td valign="middle"><div style="font-size:15px;font-weight:600;line-height:19px">{img(c.icon, 18)}&nbsp;{escape(c.text)}</div>
  {feels}</td>
 <td valign="middle" align="right"><div style="font-size:13px;font-weight:600;line-height:17px">{escape(c.place)}&nbsp;{img("navigation", 10)}</div>
  <div style="font-size:13px;color:rgba(255,255,255,.85);line-height:17px">{hi_lo}</div></td></tr></table></td></tr>
{rule}
<tr><td style="padding:6px 8px 6px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{hours}</tr></table></td></tr>
<tr><td style="padding:0 6px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
{stat("sunrise", clock(c.sunrise))}{stat("sunset", clock(c.sunset))}{stat("wind", c.wind)}{stat("droplet", f"{c.pop}%")}</tr></table></td></tr>
</table></td></tr>"""

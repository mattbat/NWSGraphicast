"""Regenerate the accent-style icon PNGs in assets/icons/ from the Lucide SVGs in this folder.

Usage (needs Node + Playwright with Chromium):
    python assets/icons/src/render_icons.py      # writes icons_job.json next to this file
    node -e "<see README: Icons>"                  # renders each SVG to a 72x72 transparent PNG

Accent style: the longest path (usually the cloud) stays white; the other parts take the
icon's accent colour. Single-element icons (sun, moon, droplets) are tinted whole.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
WHITE = "#ffffff"
ACCENT = {
    "sun": "#FFD15C",
    "sunrise": "#FFC56B",
    "sunset": "#FFB36B",
    "moon": "#E9E4FF",
    "cloud-sun": "#FFD15C",
    "cloud-moon": "#E9E4FF",
    "cloud-rain": "#8FD3FF",
    "cloud-drizzle": "#8FD3FF",
    "cloud-lightning": "#FFD15C",
    "cloud-hail": "#CFEFFF",
    "droplet": "#8FD3FF",
    "droplets": "#8FD3FF",
    "umbrella": "#8FD3FF",
}
WHOLE = {"sun", "moon", "droplet", "droplets"}
NO_ACCENT = {"navigation"}  # rendered plain white


def styled(name: str) -> str:
    svg = (HERE / f"{name}.svg").read_text()
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    for old, new in (
        ('stroke-width="2"', 'stroke-width="1.75"'),
        ('stroke="currentColor"', f'stroke="{WHITE}"'),
        ('width="24"', 'width="72"'),
        ('height="24"', 'height="72"'),
    ):
        svg = svg.replace(old, new)
    accent = ACCENT.get(name)
    if accent is None or name in NO_ACCENT:
        return svg
    if name in WHOLE:
        return svg.replace(f'stroke="{WHITE}"', f'stroke="{accent}"', 1)
    parts = re.findall(r"<(?:path|circle|line|polyline|rect)[^>]*/>", svg)
    base = max(parts, key=len)
    for part in parts:
        if part != base:
            svg = svg.replace(part, part.replace("/>", f' stroke="{accent}" />'), 1)
    return svg


if __name__ == "__main__":
    job = [(f.stem, styled(f.stem)) for f in sorted(HERE.glob("*.svg"))]
    (HERE / "icons_job.json").write_text(json.dumps(job))
    print(f"wrote {len(job)} icons to {HERE / 'icons_job.json'}")

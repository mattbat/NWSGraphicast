"""Render Lucide SVGs to transparent PNGs (72px = 3x of 24) in two styles via Chromium."""
import json, re, subprocess
from pathlib import Path
SRC, OUT = Path("icons_svg"), Path("icons_png"); OUT.mkdir(exist_ok=True)
WHITE = "#ffffff"
# accent for the non-base paths (base = longest path, usually the cloud)
ACCENT = {"sun": "#FFD15C", "sunrise": "#FFC56B", "sunset": "#FFB36B", "moon": "#E9E4FF", "cloud-sun": "#FFD15C",
          "cloud-moon": "#E9E4FF", "cloud-rain": "#8FD3FF", "cloud-drizzle": "#8FD3FF", "cloud-lightning": "#FFD15C",
          "cloud-hail": "#CFEFFF", "droplet": "#8FD3FF", "droplets": "#8FD3FF", "umbrella": "#8FD3FF"}
WHOLE = {"sun", "moon", "droplet", "droplets"}  # single-element icons: tint the whole icon
def styled(name, accent):
    svg = (SRC / f"{name}.svg").read_text()
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S).replace('stroke-width="2"', 'stroke-width="1.75"')
    svg = svg.replace('stroke="currentColor"', f'stroke="{WHITE}"').replace('width="24"', 'width="72"').replace('height="24"', 'height="72"')
    if accent and name in ACCENT:
        if name in WHOLE:
            svg = svg.replace(f'stroke="{WHITE}"', f'stroke="{ACCENT[name]}"', 1)
        else:
            paths = re.findall(r'<(?:path|circle|line|polyline|rect)[^>]*/>', svg)
            base = max(paths, key=len)
            for p in paths:
                if p is not base and p != base:
                    svg = svg.replace(p, p.replace("/>", f' stroke="{ACCENT[name]}" />'), 1)
    return svg
pages = []
for f in SRC.glob("*.svg"):
    for style in ("mono", "accent"):
        pages.append((f"{f.stem}_{style}", styled(f.stem, style == "accent")))
Path("icons_job.json").write_text(json.dumps(pages))

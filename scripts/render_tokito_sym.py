"""Render the deterministic rectangular Tokito compiler output as SVG.

This is a review artifact renderer, not a second symbol-layout engine: all
coordinates and pin directions come from the compiled `.tokito_sym` bytes.
"""

from __future__ import annotations

import argparse
import html
import math
import re
from pathlib import Path


RECT_RE = re.compile(
    r"\(rectangle\s+\(start\s+([-\d.]+)\s+([-\d.]+)\)\s+"
    r"\(end\s+([-\d.]+)\s+([-\d.]+)\)",
    re.MULTILINE,
)
PIN_RE = re.compile(
    r"\(pin\s+(\w+)\s+(\w+)(?:\s+hide)?\s+"
    r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)\s+"
    r"\(length\s+([-\d.]+)\)\s+"
    r"\(name\s+\"([^\"]*)\".*?\)\)\s+"
    r"\(number\s+\"([^\"]*)\"",
    re.DOTALL,
)
VALUE_RE = re.compile(r'\(property\s+"Value"\s+"([^"]+)"')


def render(source: Path, output: Path) -> None:
    text = source.read_text(encoding="utf-8")
    rectangle = RECT_RE.search(text)
    pins = list(PIN_RE.finditer(text))
    value = VALUE_RE.search(text)
    if rectangle is None or not pins or value is None:
        raise ValueError("expected one compiler rectangle, a Value property, and pins")

    x0, y0, x1, y1 = map(float, rectangle.groups())
    body_left, body_right = sorted((x0, x1))
    body_bottom, body_top = sorted((y0, y1))
    parsed = []
    all_x = [body_left, body_right]
    all_y = [body_bottom, body_top]
    for match in pins:
        electrical, _style, x, y, angle, length, name, number = match.groups()
        x, y, angle, length = float(x), float(y), int(angle), float(length)
        radians = math.radians(angle)
        bx = x + math.cos(radians) * length
        by = y + math.sin(radians) * length
        parsed.append((electrical, x, y, bx, by, angle, name, number))
        all_x.extend((x, bx))
        all_y.extend((y, by))

    scale = 30.0
    margin = 78.0
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    width = (max_x - min_x) * scale + margin * 2
    height = (max_y - min_y) * scale + margin * 2 + 42

    def sx(x: float) -> float:
        return margin + (x - min_x) * scale

    def sy(y: float) -> float:
        return margin + (max_y - y) * scale + 42

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        '<rect width="100%" height="100%" fill="#f7f8fb"/>',
        '<style>text{font-family:Inter,Arial,sans-serif;fill:#182235}.pin{stroke:#27364f;stroke-width:3}.body{fill:#fff;stroke:#182235;stroke-width:4}.name{font-size:18px;font-weight:650}.num{font-size:14px;fill:#52627a}.title{font-size:24px;font-weight:750}.meta{font-size:14px;fill:#68758a}</style>',
        f'<text x="{width / 2:.1f}" y="31" text-anchor="middle" class="title">{html.escape(value.group(1))}</text>',
        f'<text x="{width / 2:.1f}" y="53" text-anchor="middle" class="meta">native Tokito symbol · {len(parsed)} connectivity pins · layout@0.1.0</text>',
        f'<rect x="{sx(body_left):.1f}" y="{sy(body_top):.1f}" width="{(body_right-body_left)*scale:.1f}" height="{(body_top-body_bottom)*scale:.1f}" rx="5" class="body"/>',
    ]

    for electrical, x, y, bx, by, angle, name, number in parsed:
        parts.append(f'<line x1="{sx(x):.1f}" y1="{sy(y):.1f}" x2="{sx(bx):.1f}" y2="{sy(by):.1f}" class="pin"/>')
        if electrical == "no_connect":
            px, py = sx(x), sy(y)
            parts.append(f'<path d="M {px-6:.1f} {py-6:.1f} L {px+6:.1f} {py+6:.1f} M {px+6:.1f} {py-6:.1f} L {px-6:.1f} {py+6:.1f}" stroke="#bf3a4b" stroke-width="3"/>')

        if angle == 0:
            name_x, name_y, name_anchor = sx(bx) + 9, sy(by) + 6, "start"
            num_x, num_y, num_anchor = sx(x) - 10, sy(y) + 5, "end"
        elif angle == 180:
            name_x, name_y, name_anchor = sx(bx) - 9, sy(by) + 6, "end"
            num_x, num_y, num_anchor = sx(x) + 10, sy(y) + 5, "start"
        elif angle == 90:
            name_x, name_y, name_anchor = sx(bx), sy(by) - 9, "middle"
            num_x, num_y, num_anchor = sx(x), sy(y) + 20, "middle"
        else:
            name_x, name_y, name_anchor = sx(bx), sy(by) + 20, "middle"
            num_x, num_y, num_anchor = sx(x), sy(y) - 10, "middle"

        parts.append(f'<text x="{name_x:.1f}" y="{name_y:.1f}" text-anchor="{name_anchor}" class="name">{html.escape(name)}</text>')
        parts.append(f'<text x="{num_x:.1f}" y="{num_y:.1f}" text-anchor="{num_anchor}" class="num">{html.escape(number)}</text>')

    parts.append('</svg>\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.source, args.output)


if __name__ == "__main__":
    main()

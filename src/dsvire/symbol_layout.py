"""Deterministic rectangular schematic layout rendered as SVG."""

from __future__ import annotations

import html
import math
from typing import Any, Literal

Side = Literal["top", "bottom", "left", "right"]

PITCH = 1.0
PIN_LENGTH = 1.0
BODY_MARGIN = 0.8
SCALE = 36.0
PAD = 56.0


def pin_side(pin: dict[str, Any]) -> Side:
    name = str(pin["name"]).upper()
    electrical = str(pin["electrical"])
    if electrical == "power_in" and ("GND" in name or name in {"VSS", "V-", "EP", "PWRPAD", "PAD"}):
        return "bottom"
    if electrical in {"power_in", "power_out"}:
        return "top"
    if electrical in {"output", "open_collector", "open_emitter"}:
        return "right"
    return "left"


def _sort_key(pin: dict[str, Any]) -> tuple[str, int, str]:
    number = str(pin["number"])
    numeric = int(re_digits(number))
    return (str(pin.get("group") or ""), numeric, number)


def re_digits(number: str) -> str:
    digits = "".join(character for character in number if character.isdigit())
    return digits or "0"


def layout_pins(
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], tuple[float, float, float, float]]:
    buckets: dict[Side, list[dict[str, Any]]] = {
        "top": [],
        "bottom": [],
        "left": [],
        "right": [],
    }
    for pin in spec["pins"]:
        placed = dict(pin)
        placed["side"] = pin_side(pin)
        buckets[placed["side"]].append(placed)
    for side in buckets:
        buckets[side].sort(key=_sort_key)
    vertical = max(len(buckets["left"]), len(buckets["right"]), 2)
    horizontal = max(len(buckets["top"]), len(buckets["bottom"]), 1)
    body_h = max(vertical - 1, 1) * PITCH + BODY_MARGIN * 2
    body_w = max(horizontal - 1, 1) * PITCH + BODY_MARGIN * 2
    # Widen for labels.
    longest = max(len(str(pin["name"])) for pin in spec["pins"])
    body_w = max(body_w, 2.4 + longest * 0.22)
    left = -body_w / 2
    right = body_w / 2
    top = body_h / 2
    bottom = -body_h / 2

    def spaced(count: int, start: float, end: float) -> list[float]:
        if count == 1:
            return [(start + end) / 2]
        span = end - start
        return [start + span * index / (count - 1) for index in range(count)]

    laid: list[dict[str, Any]] = []
    for pin, y in zip(
        buckets["left"],
        spaced(len(buckets["left"]), top - BODY_MARGIN, bottom + BODY_MARGIN),
        strict=False,
    ):
        laid.append({**pin, "x": left, "y": y, "angle": 180, "length": PIN_LENGTH})
    for pin, y in zip(
        buckets["right"],
        spaced(len(buckets["right"]), top - BODY_MARGIN, bottom + BODY_MARGIN),
        strict=False,
    ):
        laid.append({**pin, "x": right, "y": y, "angle": 0, "length": PIN_LENGTH})
    for pin, x in zip(
        buckets["top"],
        spaced(len(buckets["top"]), left + BODY_MARGIN, right - BODY_MARGIN),
        strict=False,
    ):
        laid.append({**pin, "x": x, "y": top, "angle": 90, "length": PIN_LENGTH})
    for pin, x in zip(
        buckets["bottom"],
        spaced(len(buckets["bottom"]), left + BODY_MARGIN, right - BODY_MARGIN),
        strict=False,
    ):
        laid.append({**pin, "x": x, "y": bottom, "angle": 270, "length": PIN_LENGTH})
    return laid, (left, bottom, right, top)


def render_svg(
    spec: dict[str, Any], pins: list[dict[str, Any]], body: tuple[float, float, float, float]
) -> str:
    left, bottom, right, top = body

    extras_x: list[float] = [left, right]
    extras_y: list[float] = [bottom, top]
    drawn = []
    for pin in pins:
        angle = int(pin["angle"])
        length = float(pin["length"])
        x = float(pin["x"])
        y = float(pin["y"])
        radians = math.radians(angle)
        bx = x + math.cos(radians) * length
        by = y + math.sin(radians) * length
        drawn.append((pin, x, y, bx, by, angle))
        extras_x.extend((x, bx))
        extras_y.extend((y, by))
    min_x, max_x = min(extras_x), max(extras_x)
    min_y, max_y = min(extras_y), max(extras_y)
    width = (max_x - min_x) * SCALE + PAD * 2
    height = (max_y - min_y) * SCALE + PAD * 2 + 36

    def sx(value: float) -> float:
        return PAD + (value - min_x) * SCALE

    def sy(value: float) -> float:
        return PAD + (max_y - value) * SCALE + 28

    title = html.escape(str(spec["mpn"]))
    meta = html.escape(f"{spec['manufacturer']}, {spec['package']}, {len(pins)} pins")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{title} schematic symbol">',
        "<rect width='100%' height='100%' fill='#f4f1ea'/>",
        "<style>text{font-family:'IBM Plex Sans',ui-sans-serif,sans-serif;fill:#1c1914}.pin{stroke:#1c1914;stroke-width:2.6;fill:none}.body{fill:#fffdf8;stroke:#1c1914;stroke-width:3.2}.name{font-size:13px;font-weight:600}.num{font-size:11px;fill:#6b6458}.title{font-size:18px;font-weight:650}.meta{font-size:12px;fill:#6b6458}</style>",
        f'<text x="{width / 2:.1f}" y="22" text-anchor="middle" class="title">{title}</text>',
        f'<text x="{width / 2:.1f}" y="40" text-anchor="middle" class="meta">{meta}</text>',
        (
            f'<rect x="{sx(left):.1f}" y="{sy(top):.1f}" '
            f'width="{(right - left) * SCALE:.1f}" height="{(top - bottom) * SCALE:.1f}" '
            'rx="3" class="body"/>'
        ),
    ]
    for pin, x, y, bx, by, angle in drawn:
        name = html.escape(str(pin["name"]))
        number = html.escape(str(pin["number"]))
        parts.append(
            f'<line x1="{sx(x):.1f}" y1="{sy(y):.1f}" x2="{sx(bx):.1f}" y2="{sy(by):.1f}" class="pin"/>'
        )
        if angle == 180:
            parts.append(
                f'<text x="{sx(x) + 8:.1f}" y="{sy(y) + 4:.1f}" class="name">{name}</text>'
            )
            parts.append(
                f'<text x="{sx(bx) - 6:.1f}" y="{sy(by) - 6:.1f}" text-anchor="end" class="num">{number}</text>'
            )
        elif angle == 0:
            parts.append(
                f'<text x="{sx(x) - 8:.1f}" y="{sy(y) + 4:.1f}" text-anchor="end" class="name">{name}</text>'
            )
            parts.append(
                f'<text x="{sx(bx) + 6:.1f}" y="{sy(by) - 6:.1f}" class="num">{number}</text>'
            )
        elif angle == 90:
            parts.append(
                f'<text x="{sx(x):.1f}" y="{sy(y) + 16:.1f}" text-anchor="middle" class="name">{name}</text>'
            )
            parts.append(
                f'<text x="{sx(bx):.1f}" y="{sy(by) - 8:.1f}" text-anchor="middle" class="num">{number}</text>'
            )
        else:
            parts.append(
                f'<text x="{sx(x):.1f}" y="{sy(y) - 8:.1f}" text-anchor="middle" class="name">{name}</text>'
            )
            parts.append(
                f'<text x="{sx(bx):.1f}" y="{sy(by) + 14:.1f}" text-anchor="middle" class="num">{number}</text>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def compile_layout(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    pins, body = layout_pins(spec)
    return pins, render_svg(spec, pins, body)

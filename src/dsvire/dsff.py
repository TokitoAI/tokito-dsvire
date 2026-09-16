"""Dual-source figure fusion: PDF XObjects associated to layout boxes by geometry."""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.generic import DecodedStreamObject, IndirectObject

_NAME = re.compile(rb"/([A-Za-z0-9._-]+)")
_NUMBER = re.compile(rb"[-+]?(?:\d+\.\d*|\.\d+|\d+)")


class DsffError(ValueError):
    """XObject geometry could not be recovered without guessing."""


@dataclass(frozen=True)
class Affine:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def multiply(self, other: Affine) -> Affine:
        return Affine(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            e=self.e * other.a + self.f * other.c + other.e,
            f=self.e * other.b + self.f * other.d + other.f,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)


IDENTITY = Affine(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class XObjectFigure:
    page: int
    name: str
    bbox_norm: tuple[float, float, float, float]
    width_px: int
    height_px: int
    source: str = "xobject"


@dataclass(frozen=True)
class LayoutBox:
    page: int
    bbox_norm: tuple[float, float, float, float]
    label: str
    score: float
    source: str


@dataclass(frozen=True)
class AssociatedRegion:
    page: int
    bbox_norm: tuple[float, float, float, float]
    label: str
    source: str
    iou: float
    xobject_name: str | None


def iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_left = (left[2] - left[0]) * (left[3] - left[1])
    area_right = (right[2] - right[0]) * (right[3] - right[1])
    denom = area_left + area_right - inter
    if denom <= 0:
        return 0.0
    return inter / denom


def _stream_bytes(contents: Any) -> bytes:
    if contents is None:
        return b""
    if isinstance(contents, IndirectObject):
        contents = contents.get_object()
    if isinstance(contents, list):
        return b"\n".join(_stream_bytes(item) for item in contents)
    if isinstance(contents, DecodedStreamObject):
        return contents.get_data()
    get_data = getattr(contents, "get_data", None)
    if callable(get_data):
        return bytes(get_data())
    return b""


def _tokenize(data: bytes) -> list[bytes]:
    tokens: list[bytes] = []
    index = 0
    length = len(data)
    while index < length:
        while index < length and data[index] in b" \t\r\n":
            index += 1
        if index >= length:
            break
        if data[index : index + 1] == b"%":
            newline = data.find(b"\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if data[index : index + 1] == b"/":
            match = _NAME.match(data, index)
            if match is None:
                raise DsffError("XObject content stream contains an invalid name")
            tokens.append(match.group(0))
            index = match.end()
            continue
        if data[index : index + 1] in b"[]":
            tokens.append(data[index : index + 1])
            index += 1
            continue
        if data[index : index + 1] == b"(":
            depth = 1
            cursor = index + 1
            while cursor < length and depth:
                if data[cursor : cursor + 1] == b"\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if data[cursor : cursor + 1] == b"(":
                    depth += 1
                elif data[cursor : cursor + 1] == b")":
                    depth -= 1
                cursor += 1
            tokens.append(data[index:cursor])
            index = cursor
            continue
        match = _NUMBER.match(data, index)
        if match is not None:
            tokens.append(match.group(0))
            index = match.end()
            continue
        cursor = index
        while cursor < length and data[cursor] not in b" \t\r\n/%[]()":
            cursor += 1
        tokens.append(data[index:cursor])
        index = cursor
    return tokens


def _unit_square_bbox(
    matrix: Affine, page_width: float, page_height: float
) -> tuple[float, float, float, float]:
    corners = [matrix.apply(x, y) for x, y in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    x0, x1 = min(xs), max(xs)
    # PDF user space is bottom-left; DS-ViRe is top-left normalized.
    y_top = page_height - max(ys)
    y_bottom = page_height - min(ys)
    bbox = (
        max(0.0, min(1.0, x0 / page_width)),
        max(0.0, min(1.0, y_top / page_height)),
        max(0.0, min(1.0, x1 / page_width)),
        max(0.0, min(1.0, y_bottom / page_height)),
    )
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise DsffError("XObject CTM produced a degenerate crop")
    return bbox


def extract_xobjects(payload: bytes) -> tuple[XObjectFigure, ...]:
    if not payload.startswith(b"%PDF-"):
        raise DsffError("DSFF refused a non-PDF payload")
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
    except Exception as exc:
        raise DsffError("DSFF could not parse PDF structure") from exc
    figures: list[XObjectFigure] = []
    for page_index, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if width <= 0 or height <= 0:
            raise DsffError(f"page {page_index} has invalid media box")
        resources = page.get("/Resources")
        if isinstance(resources, IndirectObject):
            resources = resources.get_object()
        xobjects = resources.get("/XObject") if isinstance(resources, dict) else None
        if isinstance(xobjects, IndirectObject):
            xobjects = xobjects.get_object()
        if not isinstance(xobjects, dict):
            continue
        images: dict[str, tuple[int, int]] = {}
        for name, value in xobjects.items():
            target = value.get_object() if isinstance(value, IndirectObject) else value
            if not isinstance(target, dict) or target.get("/Subtype") != "/Image":
                continue
            key = str(name)[1:] if str(name).startswith("/") else str(name)
            images[key] = (int(target.get("/Width", 0)), int(target.get("/Height", 0)))
        if not images:
            continue
        tokens = _tokenize(_stream_bytes(page.get("/Contents")))
        stack = [IDENTITY]
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token == b"q":
                stack.append(stack[-1])
                index += 1
                continue
            if token == b"Q":
                if len(stack) == 1:
                    raise DsffError("unbalanced Q in content stream")
                stack.pop()
                index += 1
                continue
            if token == b"cm":
                if index < 6:
                    raise DsffError("cm is missing operands")
                try:
                    operands = [float(tokens[index - 6 + offset]) for offset in range(6)]
                except (ValueError, IndexError) as exc:
                    raise DsffError("cm operands are not numbers") from exc
                delta = Affine(*operands)
                stack[-1] = stack[-1].multiply(delta)
                index += 1
                continue
            if token == b"Do":
                if index == 0:
                    raise DsffError("Do is missing an XObject name")
                name_token = tokens[index - 1]
                if not name_token.startswith(b"/"):
                    raise DsffError("Do operand is not a name")
                name = name_token[1:].decode("ascii", errors="strict")
                if name in images:
                    width_px, height_px = images[name]
                    figures.append(
                        XObjectFigure(
                            page=page_index,
                            name=name,
                            bbox_norm=_unit_square_bbox(stack[-1], width, height),
                            width_px=width_px,
                            height_px=height_px,
                        )
                    )
                index += 1
                continue
            index += 1
    return tuple(figures)


def associate(
    figures: Sequence[XObjectFigure],
    boxes: Sequence[LayoutBox],
    *,
    minimum_iou: float = 0.5,
) -> tuple[AssociatedRegion, ...]:
    if not 0.5 <= minimum_iou <= 1.0:
        raise DsffError("DSFF association IoU must be within 0.5..=1.0")
    used_figures: set[int] = set()
    regions: list[AssociatedRegion] = []
    for box in boxes:
        best_index = -1
        best_iou = 0.0
        for index, figure in enumerate(figures):
            if index in used_figures or figure.page != box.page:
                continue
            score = iou(box.bbox_norm, figure.bbox_norm)
            if score > best_iou:
                best_iou = score
                best_index = index
        if best_index >= 0 and best_iou >= minimum_iou:
            used_figures.add(best_index)
            figure = figures[best_index]
            regions.append(
                AssociatedRegion(
                    page=box.page,
                    bbox_norm=box.bbox_norm,
                    label=box.label,
                    source="ensemble",
                    iou=round(best_iou, 6),
                    xobject_name=figure.name,
                )
            )
        else:
            regions.append(
                AssociatedRegion(
                    page=box.page,
                    bbox_norm=box.bbox_norm,
                    label=box.label,
                    source=box.source,
                    iou=round(best_iou, 6),
                    xobject_name=None,
                )
            )
    for index, figure in enumerate(figures):
        if index in used_figures:
            continue
        regions.append(
            AssociatedRegion(
                page=figure.page,
                bbox_norm=figure.bbox_norm,
                label="other",
                source="xobject",
                iou=0.0,
                xobject_name=figure.name,
            )
        )
    return tuple(regions)

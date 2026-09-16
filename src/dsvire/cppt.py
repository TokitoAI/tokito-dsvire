"""Caption-Pin-Patch Triple side channels from nearby text and pin-only OCR."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .eftri import REGION_TYPES
from .pdf_backend import PdfDocument
from .pipeline import MAX_TEXT_CHARS_PER_PAGE

CAPTION = re.compile(
    r"(?:figure|fig\.|table|tbl\.)\s+\d+[a-z]?(?:\s*[:.—-]\s*.{1,120})?",
    re.IGNORECASE,
)
PIN = re.compile(
    r"\b(?:P[A-Z]\d{1,2}|V(?:DD|SS|CC|EE|BAT|IN|OUT|REF)|GND|AGND|DGND|NRST|nRESET|RESET|SCL|SDA|SCK|MOSI|MISO|CS|NSS|TXD|RXD|N[A-Z]{1,4}\d{0,2})\b"
)


class CpptError(ValueError):
    """A CPPT side channel could not be extracted inside its contract."""


@dataclass(frozen=True)
class SideChannel:
    caption: str
    nearby_text: str
    pin_names: tuple[str, ...]
    ocr_text: str


def _clean(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > MAX_TEXT_CHARS_PER_PAGE:
        raise CpptError("side-channel text exceeds the page character cap")
    return collapsed


def nearby_text(
    payload: bytes, page_number: int, bbox_norm: tuple[float, float, float, float]
) -> str:
    x0, y0, x1, y1 = bbox_norm
    pad = 0.08
    expanded = (
        max(0.0, x0 - pad),
        max(0.0, y0 - pad),
        min(1.0, x1 + pad),
        min(1.0, y1 + pad),
    )
    with PdfDocument(payload) as document:
        if page_number < 1 or page_number > document.page_count:
            raise CpptError("CPPT page is outside the document")
        with document.load_page(page_number - 1) as page:
            clip = (
                expanded[0] * page.rect.width,
                expanded[1] * page.rect.height,
                expanded[2] * page.rect.width,
                expanded[3] * page.rect.height,
            )
            return _clean(page.text_bounded(clip))


def constrained_caption(text: str) -> str:
    match = CAPTION.search(text)
    if match is None:
        return ""
    return _clean(match.group(0))[:180]


def pin_lexicon(text: str, ocr_text: str = "") -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for source in (text, ocr_text):
        for match in PIN.findall(source):
            token = match.upper()
            if token not in seen:
                seen.add(token)
                names.append(token)
    if len(names) > 256:
        raise CpptError("pin lexicon exceeded 256 names")
    return tuple(names)


def extract_side_channel(
    payload: bytes,
    *,
    page: int,
    bbox_norm: tuple[float, float, float, float],
    region_type: str,
    ocr_text: str = "",
) -> SideChannel:
    if region_type not in REGION_TYPES:
        raise CpptError(f"unsupported region type: {region_type}")
    text = nearby_text(payload, page, bbox_norm)
    pins = pin_lexicon(text, ocr_text) if region_type in {"pinout", "table", "package"} else ()
    if region_type != "pinout" and ocr_text:
        raise CpptError("pin-only OCR is permitted on pinout crops only")
    return SideChannel(
        caption=constrained_caption(text),
        nearby_text=text,
        pin_names=pins,
        ocr_text=_clean(ocr_text) if ocr_text else "",
    )


def bm25_fields(channel: SideChannel) -> tuple[tuple[str, str], ...]:
    fields = [
        ("caption", channel.caption),
        ("nearby_text", channel.nearby_text),
        ("pin_names", " ".join(channel.pin_names)),
    ]
    return tuple((name, value) for name, value in fields if value)

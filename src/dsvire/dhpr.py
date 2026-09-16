"""PDF feature probe (DHPR): born-digital vs scan vs image-heavy routing."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from .pdf_backend import PdfBackendError, PdfDocument
from .pipeline import MAX_PAGES, MAX_TEXT_CHARS_PER_PAGE

Route = Literal["born_digital", "scan", "image_heavy", "mixed"]
PROBE_VERSION = "dsvire.dhpr@1.0.0"


class DhprError(ValueError):
    """The PDF could not be probed without violating DHPR safety bounds."""


@dataclass(frozen=True)
class DhprProbe:
    page_count: int
    text_chars: int
    pages_with_text: int
    image_xobjects: int
    font_objects: int
    text_page_ratio: float
    route: Route
    policy_version: str = PROBE_VERSION

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "policy_version": self.policy_version,
            "page_count": self.page_count,
            "text_chars": self.text_chars,
            "pages_with_text": self.pages_with_text,
            "image_xobjects": self.image_xobjects,
            "font_objects": self.font_objects,
            "text_page_ratio": self.text_page_ratio,
            "route": self.route,
        }


def _count_xobjects(resources: object, kind: str) -> int:
    if not isinstance(resources, dict):
        return 0
    bucket = resources.get("/XObject") if kind == "image" else resources.get("/Font")
    if isinstance(bucket, IndirectObject):
        bucket = bucket.get_object()
    if not isinstance(bucket, dict):
        return 0
    total = 0
    for value in bucket.values():
        target = value.get_object() if isinstance(value, IndirectObject) else value
        if not isinstance(target, dict):
            continue
        if kind == "font":
            total += 1
            continue
        if target.get("/Subtype") == "/Image":
            total += 1
    return total


def probe_pdf(payload: bytes) -> DhprProbe:
    if not payload.startswith(b"%PDF-"):
        raise DhprError("DHPR refused a non-PDF payload")
    try:
        document = PdfDocument(payload, max_pages=MAX_PAGES)
    except PdfBackendError as exc:
        raise DhprError(str(exc)) from exc
    text_chars = 0
    pages_with_text = 0
    try:
        for index in range(document.page_count):
            with document.load_page(index) as page:
                text = page.text()[:MAX_TEXT_CHARS_PER_PAGE]
            text_chars += len(text)
            if len(text.strip()) >= 32:
                pages_with_text += 1
        page_count = document.page_count
    finally:
        document.close()
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        images = 0
        fonts = 0
        for pdf_page in reader.pages:
            resources: object = pdf_page.get("/Resources")
            if isinstance(resources, IndirectObject):
                resources = resources.get_object()
            images += _count_xobjects(resources, "image")
            fonts += _count_xobjects(resources, "font")
    except Exception as exc:
        raise DhprError("DHPR could not inspect PDF resources") from exc
    ratio = pages_with_text / page_count
    if ratio >= 0.7 and fonts >= page_count and images <= page_count:
        route: Route = "born_digital"
    elif ratio <= 0.15 and images >= page_count:
        route = "scan"
    elif images > page_count * 2 and ratio >= 0.3:
        route = "image_heavy"
    else:
        route = "mixed"
    return DhprProbe(
        page_count=page_count,
        text_chars=text_chars,
        pages_with_text=pages_with_text,
        image_xobjects=images,
        font_objects=fonts,
        text_page_ratio=round(ratio, 6),
        route=route,
    )

"""Bounded, explicit PDFium boundary shared by production and evaluation code."""

from __future__ import annotations

import io
import math
from contextlib import suppress
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader

BACKEND_ID = f"pdfium-{version('pypdfium2')}"
MAX_DOCUMENT_PAGES = 2_000


class PdfBackendError(RuntimeError):
    """PDFium rejected input or could not satisfy a bounded operation."""


@dataclass(frozen=True)
class PdfRect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class PdfTextBlock:
    bbox: tuple[float, float, float, float]
    text: str


class PdfPage:
    def __init__(self, page: Any) -> None:
        self._page = page
        self.rotation = int(page.get_rotation()) % 360
        width, height = page.get_size()
        self.rect = PdfRect(0.0, 0.0, float(width), float(height))

    def close(self) -> None:
        self._page.close()

    def __enter__(self) -> PdfPage:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def text(self) -> str:
        text_page = self._page.get_textpage()
        try:
            return str(text_page.get_text_bounded()).replace("\r\n", "\n").replace("\r", "\n")
        finally:
            text_page.close()

    def text_bounded(self, bbox: tuple[float, float, float, float]) -> str:
        x0, y0, x1, y1 = self._validated_bbox(bbox)
        text_page = self._page.get_textpage()
        try:
            # DS-ViRe owns top-left coordinates. PDFium uses bottom-left coordinates.
            return (
                str(
                    text_page.get_text_bounded(
                        left=x0, bottom=self.rect.height - y1, right=x1, top=self.rect.height - y0
                    )
                )
                .replace("\r\n", "\n")
                .replace("\r", "\n")
            )
        finally:
            text_page.close()

    def blocks(self) -> list[PdfTextBlock]:
        """Return deterministic line blocks in DS-ViRe top-left coordinates."""
        text_page = self._page.get_textpage()
        try:
            count = text_page.count_chars()
            blocks: list[PdfTextBlock] = []
            chars: list[str] = []
            boxes: list[tuple[float, float, float, float]] = []

            def flush() -> None:
                text = "".join(chars).strip()
                if text and boxes:
                    raw = (
                        min(box[0] for box in boxes),
                        min(box[1] for box in boxes),
                        max(box[2] for box in boxes),
                        max(box[3] for box in boxes),
                    )
                    blocks.append(PdfTextBlock(self._display_bbox(raw), text))
                chars.clear()
                boxes.clear()

            for index in range(count):
                character = str(text_page.get_text_range(index, 1))
                if character in {"\r", "\n"}:
                    flush()
                    continue
                chars.append(character)
                with suppress(Exception):
                    # Whitespace/control characters may not own geometry. Text remains
                    # attached to the surrounding line but never fabricates a box.
                    box = tuple(float(value) for value in text_page.get_charbox(index))
                    if len(box) == 4:
                        boxes.append((box[0], box[1], box[2], box[3]))
            flush()
            return blocks
        finally:
            text_page.close()

    def _display_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        left, bottom, right, top = bbox
        if self.rotation == 0:
            return (left, self.rect.height - top, right, self.rect.height - bottom)
        if self.rotation == 90:
            return (bottom, left, top, right)
        if self.rotation == 180:
            return (
                self.rect.width - right,
                bottom,
                self.rect.width - left,
                top,
            )
        return (
            self.rect.width - top,
            self.rect.height - right,
            self.rect.width - bottom,
            self.rect.height - left,
        )

    def render_png(self, bbox: tuple[float, float, float, float], *, dpi: int) -> bytes:
        x0, y0, x1, y1 = self._validated_bbox(bbox)
        if not isinstance(dpi, int) or not 36 <= dpi <= 600:
            raise PdfBackendError("render DPI must be an integer in 36..=600")
        scale = dpi / 72.0
        crop = (x0, y0, self.rect.width - x1, self.rect.height - y1)
        bitmap = self._page.render(scale=scale, crop=crop)
        try:
            image: Image.Image = bitmap.to_pil()
            try:
                rgb = image.convert("RGB")
                try:
                    output = io.BytesIO()
                    rgb.save(output, format="PNG", optimize=False)
                    return output.getvalue()
                finally:
                    rgb.close()
            finally:
                image.close()
        finally:
            bitmap.close()

    def _validated_bbox(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
            raise PdfBackendError("PDF crop must contain four finite coordinates")
        x0, y0, x1, y1 = bbox
        if x0 < 0 or y0 < 0 or x1 > self.rect.width or y1 > self.rect.height:
            raise PdfBackendError("PDF crop lies outside the page")
        if x1 <= x0 or y1 <= y0:
            raise PdfBackendError("PDF crop must have positive area")
        return bbox


class PdfDocument:
    def __init__(self, payload: bytes, *, max_pages: int = MAX_DOCUMENT_PAGES) -> None:
        self._document: Any | None = None
        try:
            self._document = pdfium.PdfDocument(payload)
            page_count = len(self._document)
            if not 1 <= page_count <= max_pages:
                raise PdfBackendError(f"PDF page count {page_count} outside 1..={max_pages}")
        except PdfBackendError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            message = str(exc).casefold()
            if "password" in message:
                raise PdfBackendError("encrypted PDFs are not accepted") from exc
            if b"\nxref\n" in payload or b"\ntrailer\n" in payload or b"startxref" in payload:
                raise PdfBackendError("PDF required parser repair and was rejected") from exc
            raise PdfBackendError("PDF parser rejected input") from exc
        security_revision = int(pdfium.raw.FPDF_GetSecurityHandlerRevision(self._document.raw))
        if security_revision >= 0:
            # PDFium opened the file with no supplied password, so this is a
            # readable permission-encrypted document rather than a password gate.
            # pypdf delegates AES inspection to an optional crypto package; avoid
            # adding that attack surface and keep this bounded branch in PDFium.
            return
        try:
            strict = PdfReader(io.BytesIO(payload), strict=True)
            _ = len(strict.pages)
        except PdfBackendError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            if b"\nxref\n" in payload or b"\ntrailer\n" in payload or b"startxref" in payload:
                raise PdfBackendError("PDF required parser repair and was rejected") from exc
            raise PdfBackendError("PDF parser rejected input") from exc

    @property
    def page_count(self) -> int:
        if self._document is None:
            return 0
        return len(self._document)

    def load_page(self, index: int) -> PdfPage:
        if self._document is None:
            raise PdfBackendError("PDF document is closed")
        try:
            return PdfPage(self._document[index])
        except Exception as exc:
            raise PdfBackendError(f"PDF page {index + 1} could not be loaded") from exc

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
            self._document = None

    def __enter__(self) -> PdfDocument:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

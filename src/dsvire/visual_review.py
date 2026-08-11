"""Deterministic contact sheets for human review of visual-registry crops."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from .visual_adapters import AdapterError, render_registered_crop
from .visual_registry import VisualDocument

THUMBNAIL_SIZE = (900, 620)
CARD_SIZE = (940, 700)
SHEET_COLUMNS = 2
_SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")


def review_sheet_filename(document_id: str) -> str:
    """Return a filesystem-safe, collision-resistant contact-sheet name."""
    slug = _SAFE_FILENAME.sub("-", document_id).strip(".-") or "document"
    suffix = hashlib.sha256(document_id.encode()).hexdigest()[:10]
    return f"{slug[:100]}-{suffix}.png"


def render_review_sheet(pdf_bytes: bytes, annotation: VisualDocument) -> bytes:
    """Render every registered case with its ground-truth review caption."""
    if hashlib.sha256(pdf_bytes).hexdigest() != annotation.content_sha256:
        raise AdapterError(f"{annotation.document_id}: source SHA-256 mismatch")
    try:
        import pymupdf
        from PIL import Image, ImageDraw, ImageFont

        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except ImportError as exc:
        raise AdapterError("install tokito-dsvire[visual] to render review sheets") from exc
    except Exception as exc:
        raise AdapterError("PDF parser rejected review input") from exc
    try:
        if document.is_repaired:
            raise AdapterError("review PDF required parser repair")
        if document.needs_pass:
            raise AdapterError("encrypted review PDFs are not accepted")
        cards = []
        font = ImageFont.load_default(size=18)
        for case in annotation.cases:
            with Image.open(io.BytesIO(render_registered_crop(document, case))) as crop:
                rendered = crop.convert("RGB")
                rendered.thumbnail(THUMBNAIL_SIZE)
                card = Image.new("RGB", CARD_SIZE, "white")
            card.paste(rendered, ((CARD_SIZE[0] - rendered.width) // 2, 70))
            caption = (
                f"{annotation.document_id}/{case.case_id} | {case.label} | "
                f"{case.region_type} | page {case.page} | view={case.view}"
            )
            ImageDraw.Draw(card).text((16, 18), caption, fill="black", font=font)
            cards.append(card)
        rows = (len(cards) + SHEET_COLUMNS - 1) // SHEET_COLUMNS
        sheet = Image.new(
            "RGB",
            (CARD_SIZE[0] * SHEET_COLUMNS, CARD_SIZE[1] * rows),
            (224, 224, 224),
        )
        for index, card in enumerate(cards):
            sheet.paste(
                card,
                ((index % SHEET_COLUMNS) * CARD_SIZE[0], (index // SHEET_COLUMNS) * CARD_SIZE[1]),
            )
        output = io.BytesIO()
        sheet.save(output, format="PNG", optimize=True)
        return output.getvalue()
    finally:
        document.close()


def write_review_sheet(pdf_bytes: bytes, annotation: VisualDocument, output_dir: Path) -> Path:
    """Atomically write one contact sheet and return its final path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / review_sheet_filename(annotation.document_id)
    temporary = destination.with_suffix(".png.part")
    try:
        temporary.write_bytes(render_review_sheet(pdf_bytes, annotation))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination

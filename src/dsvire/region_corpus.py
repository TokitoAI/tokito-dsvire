"""Build a leakage-safe region corpus from DHPR, layout, and DSFF."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from .dhpr import DhprProbe, probe_pdf
from .dsff import AssociatedRegion, LayoutBox, associate, extract_xobjects
from .layout_detect import LayoutDetector, detect_document
from .pdf_backend import BACKEND_ID, PdfDocument
from .pipeline import MAX_PAGES
from .sealed_holdout import SealedHoldout, leakage_hits
from .training_corpus import CorpusRecord

REGION_CORPUS_VERSION = "dsvire.region-corpus.v1"
TOC_HINTS = (
    "pin configuration",
    "pin assignment",
    "terminal configuration",
    "package information",
    "mechanical data",
    "timing requirements",
    "typical application",
)


class RegionCorpusError(ValueError):
    """Region corpus construction refused unsafe or leaked input."""


@dataclass(frozen=True)
class RegionRecord:
    document_sha256: str
    region_id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    layout_label: str
    source: str
    dhpr_route: str
    renderer: str
    detector_id: str
    content_sha256: str


def _region_id(document_sha256: str, page: int, bbox: tuple[float, float, float, float]) -> str:
    payload = json.dumps(
        {"d": document_sha256, "p": page, "b": [round(v, 6) for v in bbox]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "r_" + hashlib.sha256(payload).hexdigest()[:16]


def toc_page_backfill(payload: bytes) -> tuple[LayoutBox, ...]:
    """Force a full-page region when layout misses a pin/package heading page."""
    with PdfDocument(payload, max_pages=MAX_PAGES) as document:
        boxes: list[LayoutBox] = []
        for index in range(document.page_count):
            with document.load_page(index) as page:
                text = page.text().casefold()
            if any(hint in text for hint in TOC_HINTS):
                boxes.append(
                    LayoutBox(
                        page=index + 1,
                        bbox_norm=(0.0, 0.0, 1.0, 1.0),
                        label="figure",
                        score=0.0,
                        source="toc_backfill",
                    )
                )
    return tuple(boxes)


def build_region_records(
    payload: bytes,
    record: CorpusRecord,
    *,
    detector: LayoutDetector,
    holdout: SealedHoldout,
    dpi: int = 150,
) -> tuple[DhprProbe, tuple[RegionRecord, ...]]:
    hits = leakage_hits(
        holdout,
        url=record.final_url,
        content_sha256=record.content_sha256,
        identity_text=(record.manufacturer, *record.symbols),
    )
    if hits:
        raise RegionCorpusError(f"refusing sealed evaluation PDF: {','.join(hits)}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != record.content_sha256:
        raise RegionCorpusError("PDF digest does not match the corpus record")
    probe = probe_pdf(payload)
    boxes = list(detect_document(payload, detector, dpi=dpi))
    if not any(box.source != "toc_backfill" for box in boxes):
        boxes.extend(toc_page_backfill(payload))
    figures = extract_xobjects(payload)
    associated = associate(figures, boxes)
    regions = tuple(_materialize(payload, record, probe, detector.detector_id, associated, dpi))
    if not regions:
        raise RegionCorpusError("no regions survived DHPR/layout/DSFF")
    return probe, regions


def _materialize(
    payload: bytes,
    record: CorpusRecord,
    probe: DhprProbe,
    detector_id: str,
    associated: Sequence[AssociatedRegion],
    dpi: int,
) -> list[RegionRecord]:
    built: list[RegionRecord] = []
    seen: set[str] = set()
    with PdfDocument(payload, max_pages=MAX_PAGES) as document:
        for item in associated:
            region_id = _region_id(record.content_sha256, item.page, item.bbox_norm)
            if region_id in seen:
                continue
            seen.add(region_id)
            with document.load_page(item.page - 1) as page:
                x0, y0, x1, y1 = item.bbox_norm
                clip = (
                    x0 * page.rect.width,
                    y0 * page.rect.height,
                    x1 * page.rect.width,
                    y1 * page.rect.height,
                )
                crop = page.render_png(clip, dpi=dpi)
            built.append(
                RegionRecord(
                    document_sha256=record.content_sha256,
                    region_id=region_id,
                    page=item.page,
                    bbox_norm=item.bbox_norm,
                    layout_label=item.label,
                    source=item.source,
                    dhpr_route=probe.route,
                    renderer=BACKEND_ID,
                    detector_id=detector_id,
                    content_sha256=hashlib.sha256(crop).hexdigest(),
                )
            )
    return built

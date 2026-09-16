"""Layout detection boundary: DocLayout-YOLO primary, MinerU fallback, fail closed."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .dsff import LayoutBox
from .pdf_backend import BACKEND_ID, PdfBackendError, PdfDocument
from .pipeline import MAX_PAGES, MAX_RENDER_PIXELS, MAX_RENDER_SIDE_PIXELS

LAYOUT_DPI = 150
REGION_LABELS = frozenset({"figure", "table"})


class LayoutDetectError(RuntimeError):
    """Layout detection cannot proceed without a pinned, verified detector."""


class LayoutDetector(Protocol):
    @property
    def detector_id(self) -> str: ...

    @property
    def model_sha256(self) -> str: ...

    def detect(self, png: bytes, *, page: int) -> Sequence[LayoutBox]: ...


def render_page_png(payload: bytes, page_number: int, *, dpi: int = LAYOUT_DPI) -> bytes:
    if dpi not in {150, 300}:
        raise LayoutDetectError("production layout renders are only 150 or 300 DPI")
    try:
        with PdfDocument(payload, max_pages=MAX_PAGES) as document:
            if page_number < 1 or page_number > document.page_count:
                raise LayoutDetectError(f"page {page_number} is outside the document")
            with document.load_page(page_number - 1) as page:
                width = page.rect.width * dpi / 72
                height = page.rect.height * dpi / 72
                if (
                    width > MAX_RENDER_SIDE_PIXELS
                    or height > MAX_RENDER_SIDE_PIXELS
                    or width * height > MAX_RENDER_PIXELS
                ):
                    raise LayoutDetectError("layout render exceeds safety limits")
                return page.render_png((0.0, 0.0, page.rect.width, page.rect.height), dpi=dpi)
    except PdfBackendError as exc:
        raise LayoutDetectError(str(exc)) from exc


def _validated_boxes(
    boxes: Sequence[LayoutBox], *, page: int, source: str
) -> tuple[LayoutBox, ...]:
    result: list[LayoutBox] = []
    for box in boxes:
        if box.page != page:
            raise LayoutDetectError("detector returned a box for the wrong page")
        x0, y0, x1, y1 = box.bbox_norm
        if not 0.0 <= x0 < x1 <= 1.0 or not 0.0 <= y0 < y1 <= 1.0:
            raise LayoutDetectError("layout box is not a normalized positive rectangle")
        if not 0.0 <= box.score <= 1.0:
            raise LayoutDetectError("layout score must be within 0..=1")
        if box.source != source:
            raise LayoutDetectError("layout box source does not match the detector")
        result.append(box)
    return tuple(result)


@dataclass(frozen=True)
class OnnxLayoutDetector:
    """Pinned ONNX DocLayout-YOLO. Construction verifies bytes; it never downloads."""

    model_path: Path
    model_sha256: str
    expected_bytes: int
    score_threshold: float = 0.4

    def __post_init__(self) -> None:
        if not 0.2 <= self.score_threshold <= 0.9:
            raise LayoutDetectError("DocLayout-YOLO score threshold is outside 0.2..=0.9")
        if not self.model_path.is_file():
            raise LayoutDetectError(f"DocLayout-YOLO weights are missing: {self.model_path}")
        if self.model_path.stat().st_size != self.expected_bytes:
            raise LayoutDetectError("DocLayout-YOLO size does not match the pinned artifact")
        with self.model_path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != self.model_sha256:
            raise LayoutDetectError("DocLayout-YOLO SHA-256 does not match the pinned artifact")

    @property
    def detector_id(self) -> str:
        return f"doclayout-yolo-onnx@{self.model_sha256[:12]}-{BACKEND_ID}-{LAYOUT_DPI}dpi"

    def detect(self, png: bytes, *, page: int) -> Sequence[LayoutBox]:
        try:
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        except ImportError as exc:
            raise LayoutDetectError("install tokito-dsvire[visual] for DocLayout-YOLO") from exc
        session = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
        with Image.open(io.BytesIO(png)) as image:
            rgb = image.convert("RGB")
            array = np.asarray(rgb, dtype=np.float32)
            rgb.close()
        if array.ndim != 3:
            raise LayoutDetectError("layout render is not an RGB image")
        height, width, _ = array.shape
        tensor = np.transpose(array / 255.0, (2, 0, 1))[None, ...]
        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: tensor})
        if not outputs:
            return ()
        detections = outputs[0]
        boxes: list[LayoutBox] = []
        for row in np.atleast_2d(detections):
            if row.size < 6:
                continue
            x0, y0, x1, y1, score, class_id = (
                float(row[0]),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                int(row[5]),
            )
            if score < self.score_threshold:
                continue
            label = (
                "figure" if class_id in {3, 4} else "table" if class_id in {5, 6, 7} else "other"
            )
            if label not in REGION_LABELS:
                continue
            boxes.append(
                LayoutBox(
                    page=page,
                    bbox_norm=(
                        max(0.0, min(1.0, x0 / width)),
                        max(0.0, min(1.0, y0 / height)),
                        max(0.0, min(1.0, x1 / width)),
                        max(0.0, min(1.0, y1 / height)),
                    ),
                    label=label,
                    score=min(1.0, max(0.0, score)),
                    source="doclayout_yolo",
                )
            )
        return _validated_boxes(boxes, page=page, source="doclayout_yolo")


class MinerULayoutDetector:
    """Optional MinerU fallback. Fail closed if the extra is absent."""

    @property
    def detector_id(self) -> str:
        return "mineru-layout-fallback@unpinned-refused"

    @property
    def model_sha256(self) -> str:
        raise LayoutDetectError(
            "MinerU fallback requires a pinned model digest before production use"
        )

    def detect(self, png: bytes, *, page: int) -> Sequence[LayoutBox]:
        del png, page
        raise LayoutDetectError(
            "MinerU fallback is not enabled until a pinned model digest and license review land"
        )


def detect_document(
    payload: bytes,
    detector: LayoutDetector,
    *,
    fallback: LayoutDetector | None = None,
    dpi: int = LAYOUT_DPI,
) -> tuple[LayoutBox, ...]:
    try:
        with PdfDocument(payload, max_pages=MAX_PAGES) as document:
            page_count = document.page_count
    except PdfBackendError as exc:
        raise LayoutDetectError(str(exc)) from exc
    boxes: list[LayoutBox] = []
    for page in range(1, page_count + 1):
        png = render_page_png(payload, page, dpi=dpi)
        detected = tuple(detector.detect(png, page=page))
        if not detected and fallback is not None:
            detected = tuple(fallback.detect(png, page=page))
        boxes.extend(detected)
    return tuple(boxes)

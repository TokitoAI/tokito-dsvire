"""Candidate adapters for the visual-verifier benchmark.

Adapters see the requested identity, region type, view, and crop. They never see
the registry's positive/negative label. Ground truth remains exclusively in the
registry and is joined to adapter scores only after inference.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
from functools import cached_property
from importlib.metadata import version
from importlib.resources import files
from typing import Protocol

from .pipeline import (
    MAX_PAGES,
    MAX_RENDER_PIXELS,
    MAX_RENDER_SIDE_PIXELS,
    MAX_TEXT_CHARS_PER_PAGE,
    RENDER_DPI,
    _contains_exact_mpn,
    _contains_ordered_tokens,
    _contains_phrase,
    score_candidate,
)
from .visual_registry import VisualCase, VisualDocument

TEXT_LAYOUT_ADAPTER_ID = "dsvire.visual-adapter.text-layout@1.0.0"
RAPID_OCR_ADAPTER_ID = "dsvire.visual-adapter.rapidocr@1.1.0"


class AdapterError(RuntimeError):
    """An adapter could not safely score the registered document/case."""


@dataclasses.dataclass(frozen=True)
class AdapterMetadata:
    adapter_id: str
    implementation_sha256: str
    model_sha256: str | None
    preprocessing_id: str
    score_semantics: str


class VisualAdapter(Protocol):
    @property
    def metadata(self) -> AdapterMetadata: ...

    def score(self, document: object, case: VisualCase) -> float: ...


class TextLayoutAdapter:
    """Deterministic non-visual baseline over PDF text inside the labeled crop.

    This is an honest comparator, not EGVV: its metadata declares similarity
    semantics and its ID explicitly says text-layout. It measures how much a
    real visual/OCR adapter improves over the production heuristic family.
    """

    @cached_property
    def metadata(self) -> AdapterMetadata:
        implementation = "\n".join(
            inspect.getsource(component).replace("\r\n", "\n")
            for component in (
                TextLayoutAdapter,
                score_candidate,
                _contains_exact_mpn,
                _contains_ordered_tokens,
                _contains_phrase,
            )
        ).encode()
        digest = hashlib.sha256(implementation).hexdigest()
        return AdapterMetadata(
            TEXT_LAYOUT_ADAPTER_ID,
            digest,
            None,
            f"pymupdf-{version('PyMuPDF')}-clip-text-normalized-bbox@1",
            "similarity",
        )

    def score(self, document: object, case: VisualCase) -> float:
        page_count = getattr(document, "page_count", 0)
        if not isinstance(page_count, int) or page_count < 1 or page_count > MAX_PAGES:
            raise AdapterError(f"PDF page count {page_count} outside 1..={MAX_PAGES}")
        if case.page > page_count:
            raise AdapterError(
                f"case {case.case_id!r} references page {case.page}, PDF has {page_count}"
            )
        try:
            import pymupdf

            page = document.load_page(case.page - 1)
            x0, y0, x1, y1 = case.bbox_norm
            clip = pymupdf.Rect(
                x0 * float(page.rect.width),
                y0 * float(page.rect.height),
                x1 * float(page.rect.width),
                y1 * float(page.rect.height),
            )
            text = str(page.get_text("text", clip=clip, sort=True))
        except Exception as exc:
            raise AdapterError(f"failed to read registered crop for {case.case_id!r}") from exc
        if len(text) > MAX_TEXT_CHARS_PER_PAGE:
            raise AdapterError(f"registered crop text exceeds {MAX_TEXT_CHARS_PER_PAGE} characters")

        return _semantic_score(text, case)


def _semantic_score(text: str, case: VisualCase) -> float:
    if case.region_type == "package":
        # Manufacturer branding frequently sits outside an orderable-part row.
        # Identity reconciliation owns manufacturer proof; this crop score asks
        # whether the exact MPN/package pair is present.
        score = (
            float(_contains_exact_mpn(text, case.claimed_identity.mpn))
            + float(_contains_ordered_tokens(text, case.claimed_identity.package))
        ) / 2
    else:
        score, _verified = score_candidate(case.region_type, text)
    if case.view in {"top", "bottom"}:
        score *= float(_contains_phrase(text, f"{case.view} view"))
    return round(min(1.0, max(0.0, score)), 6)


def _implementation_digest(*components: object) -> str:
    source = "\n".join(
        inspect.getsource(component).replace("\r\n", "\n") for component in components
    ).encode()
    return hashlib.sha256(source).hexdigest()


def _rapidocr_model_digest() -> str:
    try:
        model_dir = files("rapidocr").joinpath("models")
        models = sorted(
            (item for item in model_dir.iterdir() if item.name.casefold().endswith(".onnx")),
            key=lambda item: item.name,
        )
        if not models:
            raise AdapterError("RapidOCR package contains no ONNX model files")
        digest = hashlib.sha256()
        for model in models:
            digest.update(model.name.encode())
            digest.update(model.read_bytes())
        return digest.hexdigest()
    except (ImportError, OSError) as exc:
        raise AdapterError("RapidOCR model files are unavailable") from exc


def _stable_rapidocr_score(value: float) -> float:
    """Remove sub-precision ONNX CPU scheduling noise from comparator output."""
    return round(value, 5)


class RapidOcrAdapter:
    """CPU-capable pixel OCR comparator backed by bundled RapidOCR ONNX models.

    OCR reads the rendered crop, not the PDF text layer. Its confidence only
    attenuates a structural similarity score; it is not treated as a calibrated
    probability until a separate held-out calibration policy proves that claim.
    """

    def __init__(self, engine: object | None = None) -> None:
        if engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise AdapterError("install tokito-dsvire[visual] for RapidOCR") from exc
            engine = RapidOCR(
                params={
                    "EngineConfig.onnxruntime.intra_op_num_threads": 1,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                }
            )
        self._engine = engine

    @cached_property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            RAPID_OCR_ADAPTER_ID,
            _implementation_digest(
                RapidOcrAdapter,
                _semantic_score,
                _contains_exact_mpn,
                _contains_ordered_tokens,
                _contains_phrase,
                score_candidate,
                _stable_rapidocr_score,
            ),
            _rapidocr_model_digest(),
            (
                f"rapidocr-{version('rapidocr')}-onnxruntime-{version('onnxruntime')}-"
                f"pymupdf-{version('PyMuPDF')}-rgb-{RENDER_DPI}dpi-"
                "onnx-cpu-single-thread-score-5dp@2"
            ),
            "similarity",
        )

    def score(self, document: object, case: VisualCase) -> float:
        page_count = getattr(document, "page_count", 0)
        if not isinstance(page_count, int) or page_count < 1 or page_count > MAX_PAGES:
            raise AdapterError(f"PDF page count {page_count} outside 1..={MAX_PAGES}")
        if case.page > page_count:
            raise AdapterError(
                f"case {case.case_id!r} references page {case.page}, PDF has {page_count}"
            )
        try:
            import pymupdf

            page = document.load_page(case.page - 1)
            x0, y0, x1, y1 = case.bbox_norm
            width = (x1 - x0) * float(page.rect.width) * RENDER_DPI / 72
            height = (y1 - y0) * float(page.rect.height) * RENDER_DPI / 72
            if (
                width <= 0
                or height <= 0
                or width > MAX_RENDER_SIDE_PIXELS
                or height > MAX_RENDER_SIDE_PIXELS
                or width * height > MAX_RENDER_PIXELS
            ):
                raise AdapterError("registered crop exceeds render safety limit")
            clip = pymupdf.Rect(
                x0 * float(page.rect.width),
                y0 * float(page.rect.height),
                x1 * float(page.rect.width),
                y1 * float(page.rect.height),
            )
            image = page.get_pixmap(clip=clip, dpi=RENDER_DPI, alpha=False).tobytes("png")
            result = self._engine(image)
            texts = tuple(getattr(result, "txts", ()) or ())
            confidences = tuple(getattr(result, "scores", ()) or ())
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"OCR failed for registered crop {case.case_id!r}") from exc
        if len(texts) != len(confidences):
            raise AdapterError("OCR returned mismatched text and confidence arrays")
        if not texts:
            return 0.0
        text = "\n".join(str(value) for value in texts)
        if len(text) > MAX_TEXT_CHARS_PER_PAGE:
            raise AdapterError("OCR text exceeds safety limit")
        weights = [max(1, len(str(value))) for value in texts]
        confidence = sum(
            float(score) * weight for score, weight in zip(confidences, weights, strict=True)
        ) / sum(weights)
        if not 0 <= confidence <= 1:
            raise AdapterError("OCR confidence must be within 0..=1")
        return _stable_rapidocr_score(_semantic_score(text, case) * confidence)


def score_document(
    adapter: VisualAdapter, pdf_bytes: bytes, annotation: VisualDocument
) -> dict[str, float]:
    """Score every registered case after verifying the exact source bytes."""
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    if digest != annotation.content_sha256:
        raise AdapterError(
            f"{annotation.document_id}: source SHA-256 mismatch; "
            f"expected {annotation.content_sha256}, got {digest}"
        )
    try:
        import pymupdf

        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise AdapterError("PDF parser rejected benchmark input") from exc
    try:
        if document.is_repaired:
            raise AdapterError("benchmark PDF required parser repair")
        if document.needs_pass:
            raise AdapterError("encrypted benchmark PDFs are not accepted")
        return {
            f"{annotation.document_id}/{case.case_id}": adapter.score(document, case)
            for case in annotation.cases
        }
    finally:
        document.close()

"""Candidate adapters for the visual-verifier benchmark.

Adapters see the requested identity, region type, view, and crop. They never see
the registry's positive/negative label. Ground truth remains exclusively in the
registry and is joined to adapter scores only after inference.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
from importlib.metadata import version
from typing import Protocol

from .pipeline import (
    MAX_PAGES,
    MAX_TEXT_CHARS_PER_PAGE,
    _contains_exact_mpn,
    _contains_ordered_tokens,
    _contains_phrase,
    score_candidate,
)
from .visual_registry import VisualCase, VisualDocument

TEXT_LAYOUT_ADAPTER_ID = "dsvire.visual-adapter.text-layout@1.0.0"


class AdapterError(RuntimeError):
    """An adapter could not safely score the registered document/case."""


@dataclasses.dataclass(frozen=True)
class AdapterMetadata:
    adapter_id: str
    implementation_sha256: str
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

    @property
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

        if case.region_type == "package":
            # Manufacturer branding frequently sits outside an orderable-part
            # row. The identity reconciliation stage owns manufacturer proof;
            # this crop score asks whether the exact MPN/package pair is here.
            score = (
                float(_contains_exact_mpn(text, case.claimed_identity.mpn))
                + float(_contains_ordered_tokens(text, case.claimed_identity.package))
            ) / 2
        else:
            score, _verified = score_candidate(case.region_type, text)

        if case.view in {"top", "bottom"}:
            requested_view_present = _contains_phrase(text, f"{case.view} view")
            score *= float(requested_view_present)
        return round(min(1.0, max(0.0, score)), 6)


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

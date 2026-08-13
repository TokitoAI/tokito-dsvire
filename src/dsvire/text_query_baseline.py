"""Query-conditioned text/metadata baseline over registered region candidates."""

from __future__ import annotations

import hashlib
import inspect
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .corpus_coverage import QueryRecord
from .pdf_backend import BACKEND_ID
from .pipeline import MAX_PAGES, MAX_TEXT_CHARS_PER_PAGE
from .visual_registry import VisualCase, VisualDocument

SYSTEM_ID = "dsvire.query-baseline.text-layout-metadata@2.0.0"
TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"a", "an", "the", "find", "show", "where", "is", "of", "for"}


class TextQueryBaselineError(RuntimeError):
    """Registered source/crop text could not be processed safely."""


class PdfDocument(Protocol):
    @property
    def page_count(self) -> int: ...

    def load_page(self, page_id: int) -> Any: ...


@dataclass(frozen=True)
class CandidateText:
    case_id: str
    document: VisualDocument
    case: VisualCase
    text: str


def implementation_sha256() -> str:
    source = "\n".join(
        inspect.getsource(component).replace("\r\n", "\n")
        for component in (extract_candidate_text, score_query_candidate, _tokens)
    ).encode()
    source += f"\n{BACKEND_ID}".encode()
    return hashlib.sha256(source).hexdigest()


def extract_candidate_text(pdf: PdfDocument, document: VisualDocument, case: VisualCase) -> str:
    page_count = pdf.page_count
    if not isinstance(page_count, int) or page_count < 1 or page_count > MAX_PAGES:
        raise TextQueryBaselineError(f"PDF page count {page_count} outside 1..={MAX_PAGES}")
    if case.page > page_count:
        raise TextQueryBaselineError(
            f"{document.document_id}/{case.case_id} references missing page {case.page}"
        )
    try:
        page: Any = pdf.load_page(case.page - 1)
        x0, y0, x1, y1 = case.bbox_norm
        clip = (
            x0 * float(page.rect.width),
            y0 * float(page.rect.height),
            x1 * float(page.rect.width),
            y1 * float(page.rect.height),
        )
        try:
            text = str(page.text_bounded(clip))
        finally:
            page.close()
    except Exception as exc:
        raise TextQueryBaselineError(
            f"failed to extract {document.document_id}/{case.case_id}"
        ) from exc
    if len(text) > MAX_TEXT_CHARS_PER_PAGE:
        raise TextQueryBaselineError("candidate crop text exceeds safety limit")
    return text


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN.findall(value.casefold()) if token not in STOP}


def score_query_candidate(query: QueryRecord, candidate: CandidateText) -> float:
    """Score without consulting the candidate's ground-truth relevance label."""
    query_tokens = _tokens(query.query_text)
    text_tokens = _tokens(candidate.text)
    mpn_tokens = _tokens(candidate.document.identity.mpn)
    package_tokens = _tokens(candidate.document.identity.package)
    identity = float(bool(mpn_tokens) and mpn_tokens <= query_tokens)
    package = float(bool(package_tokens) and package_tokens <= query_tokens)
    intent = float(candidate.case.region_type == query.query_type)
    lexical = len(query_tokens & text_tokens) / len(query_tokens) if query_tokens else 0.0
    score = 4.0 * identity + package + 2.0 * intent + lexical
    if not math.isfinite(score):
        raise TextQueryBaselineError("baseline produced a non-finite score")
    return round(score, 6)

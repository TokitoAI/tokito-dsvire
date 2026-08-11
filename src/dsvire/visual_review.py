"""Deterministic contact sheets for human review of visual-registry crops."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .visual_adapters import AdapterError, render_registered_crop
from .visual_metrics import ALLOWED_LABELS
from .visual_registry import (
    ALLOWED_REGION_TYPES,
    ALLOWED_VIEWS,
    VisualDocument,
    VisualRegistry,
    load_visual_registry_data,
)

THUMBNAIL_SIZE = (900, 620)
CARD_SIZE = (940, 700)
SHEET_COLUMNS = 2
_SAFE_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
REVIEW_PACKET_VERSION = "dsvire.visual-review-packet.v1"
REVIEW_DECISION_VERSION = "dsvire.visual-review-decision.v1"
MAX_GITHUB_REVIEW_BYTES = 1_000_000
_GITHUB_REVIEW_URL = re.compile(
    r"https://github\.com/TokitoAI/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<pr>[1-9][0-9]*)"
    r"#pullrequestreview-(?P<review>[1-9][0-9]*)"
)


class VisualReviewError(ValueError):
    """A review packet, decision, or application violated the review contract."""


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _strict(value: Mapping[str, Any], keys: set[str], context: str) -> None:
    missing = keys - set(value)
    unknown = set(value) - keys
    if missing or unknown:
        raise VisualReviewError(
            f"{context} keys invalid: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualReviewError(f"{context} must be non-empty text")
    return value.strip()


def _digest(value: Any, context: str) -> str:
    digest = _text(value, context)
    if _SHA256.fullmatch(digest) is None:
        raise VisualReviewError(f"{context} must be lowercase SHA-256")
    return digest


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
    handle, temporary_name = tempfile.mkstemp(
        dir=output_dir, prefix=f".{destination.name}.", suffix=".part"
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(render_review_sheet(pdf_bytes, annotation))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def fetch_github_review_provenance(review_url: str, token: str | None = None) -> dict[str, Any]:
    """Fetch one bounded TokitoAI pull-request review from GitHub's API."""
    match = _GITHUB_REVIEW_URL.fullmatch(review_url)
    if match is None:
        raise VisualReviewError("review URL must identify a TokitoAI pull-request review")
    api_url = (
        f"https://api.github.com/repos/TokitoAI/{match['repo']}/pulls/"
        f"{match['pr']}/reviews/{match['review']}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tokito-dsvire-review/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.geturl() != api_url:
                raise VisualReviewError("GitHub review API redirected unexpectedly")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > MAX_GITHUB_REVIEW_BYTES:
                raise VisualReviewError("GitHub review response exceeds size limit")
            payload = response.read(MAX_GITHUB_REVIEW_BYTES + 1)
    except VisualReviewError:
        raise
    except (OSError, ValueError) as exc:
        raise VisualReviewError("failed to fetch GitHub review provenance") from exc
    if len(payload) > MAX_GITHUB_REVIEW_BYTES:
        raise VisualReviewError("GitHub review response exceeds size limit")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualReviewError("GitHub review response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VisualReviewError("GitHub review response must be an object")
    return value


def verify_github_review_provenance(
    decision: Mapping[str, Any],
    loader: Callable[[str], Mapping[str, Any]],
) -> None:
    """Require an approved, author-matched GitHub review bound to the packet hash."""
    review = loader(str(decision["review_url"]))
    try:
        login = review["user"]["login"]
        state = review["state"]
        submitted_at = review["submitted_at"]
        body = review["body"] or ""
        html_url = review["html_url"]
    except (KeyError, TypeError) as exc:
        raise VisualReviewError("GitHub review provenance response is incomplete") from exc
    if login != str(decision["reviewer"]).removeprefix("github:"):
        raise VisualReviewError("GitHub review author does not match decision reviewer")
    if state != "APPROVED":
        raise VisualReviewError("GitHub review is not approved")
    if html_url != decision["review_url"]:
        raise VisualReviewError("GitHub review URL does not match API provenance")
    try:
        import datetime as dt

        decision_time = dt.datetime.fromisoformat(
            str(decision["reviewed_at"]).replace("Z", "+00:00")
        )
        github_time = dt.datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisualReviewError("GitHub review submitted_at is not ISO-8601") from exc
    if decision_time != github_time:
        raise VisualReviewError("GitHub review time does not match decision reviewed_at")
    marker = f"DSVIRE_REVIEW_PACKET_SHA256={decision['packet_sha256']}"
    if marker not in body:
        raise VisualReviewError("GitHub approval does not bind the review packet digest")


def build_review_packet(
    registry: VisualRegistry,
    pdf_loader: Callable[[VisualDocument], bytes],
    *,
    document_ids: set[str] | None = None,
) -> dict[str, object]:
    """Build a deterministic manifest binding exact registry annotations to crop bytes."""
    known_ids = {document.document_id for document in registry.documents}
    selected = known_ids if document_ids is None else set(document_ids)
    if not selected:
        raise VisualReviewError("review packet must select at least one document")
    unknown = selected - known_ids
    if unknown:
        raise VisualReviewError(f"unknown review document IDs: {sorted(unknown)}")

    documents: list[dict[str, object]] = []
    for annotation in registry.documents:
        if annotation.document_id not in selected:
            continue
        if annotation.review.status != "unreviewed":
            raise VisualReviewError(
                f"{annotation.document_id}: only unreviewed annotations may be exported"
            )
        payload = pdf_loader(annotation)
        if hashlib.sha256(payload).hexdigest() != annotation.content_sha256:
            raise VisualReviewError(f"{annotation.document_id}: source SHA-256 mismatch")
        try:
            import pymupdf

            document = pymupdf.open(stream=payload, filetype="pdf")
        except Exception as exc:
            raise VisualReviewError(f"{annotation.document_id}: PDF parser rejected input") from exc
        try:
            if document.is_repaired or document.needs_pass:
                raise VisualReviewError(
                    f"{annotation.document_id}: repaired or encrypted review PDF is forbidden"
                )
            cases = [
                {
                    "case_id": f"{annotation.document_id}/{case.case_id}",
                    "label": case.label,
                    "region_type": case.region_type,
                    "page": case.page,
                    "bbox_norm": list(case.bbox_norm),
                    "view": case.view,
                    "crop_sha256": hashlib.sha256(
                        render_registered_crop(document, case)
                    ).hexdigest(),
                }
                for case in annotation.cases
            ]
        finally:
            document.close()
        documents.append(
            {
                "id": annotation.document_id,
                "source_sha256": annotation.content_sha256,
                "annotation_revision": annotation.review.annotation_revision,
                "cases": cases,
            }
        )
    payload = {
        "schema_version": REVIEW_PACKET_VERSION,
        "registry_sha256": registry.content_sha256,
        "documents": documents,
    }
    return {**payload, "packet_sha256": _canonical_sha256(payload)}


def load_review_packet_data(value: Any) -> dict[str, object]:
    """Strictly validate a review packet and its self-authenticating digest."""
    if not isinstance(value, Mapping):
        raise VisualReviewError("review packet must be an object")
    _strict(
        value,
        {"schema_version", "registry_sha256", "documents", "packet_sha256"},
        "review packet",
    )
    if value["schema_version"] != REVIEW_PACKET_VERSION:
        raise VisualReviewError("unsupported review packet schema")
    _digest(value["registry_sha256"], "review packet.registry_sha256")
    packet_digest = _digest(value["packet_sha256"], "review packet.packet_sha256")
    documents = value["documents"]
    if not isinstance(documents, list) or not documents:
        raise VisualReviewError("review packet.documents must be a non-empty array")
    document_ids: set[str] = set()
    case_ids: set[str] = set()
    for index, document in enumerate(documents):
        context = f"review packet.documents[{index}]"
        if not isinstance(document, Mapping):
            raise VisualReviewError(f"{context} must be an object")
        _strict(document, {"id", "source_sha256", "annotation_revision", "cases"}, context)
        document_id = _text(document["id"], f"{context}.id")
        if document_id in document_ids:
            raise VisualReviewError(f"duplicate review document ID: {document_id}")
        document_ids.add(document_id)
        _digest(document["source_sha256"], f"{context}.source_sha256")
        _text(document["annotation_revision"], f"{context}.annotation_revision")
        cases = document["cases"]
        if not isinstance(cases, list) or not cases:
            raise VisualReviewError(f"{context}.cases must be a non-empty array")
        for case_index, case in enumerate(cases):
            case_context = f"{context}.cases[{case_index}]"
            if not isinstance(case, Mapping):
                raise VisualReviewError(f"{case_context} must be an object")
            _strict(
                case,
                {
                    "case_id",
                    "label",
                    "region_type",
                    "page",
                    "bbox_norm",
                    "view",
                    "crop_sha256",
                },
                case_context,
            )
            case_id = _text(case["case_id"], f"{case_context}.case_id")
            if not case_id.startswith(f"{document_id}/"):
                raise VisualReviewError(f"{case_context}.case_id must belong to its document")
            if case_id in case_ids:
                raise VisualReviewError(f"duplicate review case ID: {case_id}")
            case_ids.add(case_id)
            label = _text(case["label"], f"{case_context}.label")
            if label not in ALLOWED_LABELS:
                raise VisualReviewError(f"{case_context}.label is unsupported")
            region_type = _text(case["region_type"], f"{case_context}.region_type")
            if region_type not in ALLOWED_REGION_TYPES:
                raise VisualReviewError(f"{case_context}.region_type is unsupported")
            if (
                not isinstance(case["page"], int)
                or isinstance(case["page"], bool)
                or case["page"] < 1
            ):
                raise VisualReviewError(f"{case_context}.page must be a positive integer")
            bbox = case["bbox_norm"]
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise VisualReviewError(f"{case_context}.bbox_norm must contain four values")
            if any(
                not isinstance(coordinate, (int, float))
                or isinstance(coordinate, bool)
                or not math.isfinite(coordinate)
                or not 0 <= coordinate <= 1
                for coordinate in bbox
            ):
                raise VisualReviewError(f"{case_context}.bbox_norm must be finite within 0..=1")
            if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
                raise VisualReviewError(f"{case_context}.bbox_norm must have positive area")
            view = _text(case["view"], f"{case_context}.view")
            if view not in ALLOWED_VIEWS:
                raise VisualReviewError(f"{case_context}.view is unsupported")
            _digest(case["crop_sha256"], f"{case_context}.crop_sha256")
    payload = {key: value[key] for key in ("schema_version", "registry_sha256", "documents")}
    if _canonical_sha256(payload) != packet_digest:
        raise VisualReviewError("review packet digest mismatch")
    return dict(value)


def load_review_decision_data(value: Any, packet: Mapping[str, Any]) -> dict[str, object]:
    """Validate a complete named-human decision against one exact review packet."""
    packet = load_review_packet_data(packet)
    if not isinstance(value, Mapping):
        raise VisualReviewError("review decision must be an object")
    _strict(
        value,
        {
            "schema_version",
            "packet_sha256",
            "registry_sha256",
            "reviewer",
            "reviewed_at",
            "review_url",
            "decisions",
        },
        "review decision",
    )
    if value["schema_version"] != REVIEW_DECISION_VERSION:
        raise VisualReviewError("unsupported review decision schema")
    if value["packet_sha256"] != packet["packet_sha256"]:
        raise VisualReviewError("review decision packet digest mismatch")
    if value["registry_sha256"] != packet["registry_sha256"]:
        raise VisualReviewError("review decision registry digest mismatch")
    reviewer = _text(value["reviewer"], "review decision.reviewer")
    if re.fullmatch(r"github:[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", reviewer) is None:
        raise VisualReviewError("review decision.reviewer must be github:<username>")
    reviewed_at = _text(value["reviewed_at"], "review decision.reviewed_at")
    try:
        import datetime as dt

        parsed = dt.datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisualReviewError("review decision.reviewed_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise VisualReviewError("review decision.reviewed_at must include a timezone")
    review_url = _text(value["review_url"], "review decision.review_url")
    if _GITHUB_REVIEW_URL.fullmatch(review_url) is None:
        raise VisualReviewError(
            "review decision.review_url must identify a TokitoAI pull-request review"
        )
    expected = {case["case_id"] for document in packet["documents"] for case in document["cases"]}
    decisions = value["decisions"]
    if not isinstance(decisions, list):
        raise VisualReviewError("review decision.decisions must be an array")
    observed: set[str] = set()
    for index, decision in enumerate(decisions):
        context = f"review decision.decisions[{index}]"
        if not isinstance(decision, Mapping):
            raise VisualReviewError(f"{context} must be an object")
        _strict(decision, {"case_id", "outcome", "note"}, context)
        case_id = _text(decision["case_id"], f"{context}.case_id")
        if case_id in observed:
            raise VisualReviewError(f"duplicate review decision: {case_id}")
        observed.add(case_id)
        outcome = _text(decision["outcome"], f"{context}.outcome")
        if outcome not in {"accepted", "rejected"}:
            raise VisualReviewError(f"{context}.outcome must be accepted or rejected")
        if not isinstance(decision["note"], str):
            raise VisualReviewError(f"{context}.note must be text")
        if outcome == "rejected" and not decision["note"].strip():
            raise VisualReviewError(f"{context}.note is required for rejection")
    if observed != expected:
        raise VisualReviewError(
            f"review decisions incomplete: missing={sorted(expected - observed)}, "
            f"unknown={sorted(observed - expected)}"
        )
    return dict(value)


def apply_review_decision(
    registry_data: Any,
    packet_data: Any,
    decision_data: Any,
    *,
    provenance_loader: Callable[[str], Mapping[str, Any]],
) -> dict[str, object]:
    """Apply an all-accepted decision to the exact registry revision."""
    registry = load_visual_registry_data(registry_data)
    packet = load_review_packet_data(packet_data)
    decision = load_review_decision_data(decision_data, packet)
    verify_github_review_provenance(decision, provenance_loader)
    if registry.content_sha256 != packet["registry_sha256"]:
        raise VisualReviewError("current registry does not match reviewed registry digest")
    rejected = [item["case_id"] for item in decision["decisions"] if item["outcome"] == "rejected"]
    if rejected:
        raise VisualReviewError(f"cannot apply a review containing rejections: {rejected}")

    selected = {document["id"]: document for document in packet["documents"]}
    output = json.loads(json.dumps(registry_data))
    for document in output["documents"]:
        packet_document = selected.get(document["id"])
        if packet_document is None:
            continue
        if document["review"]["status"] != "unreviewed":
            raise VisualReviewError(f"{document['id']}: annotation is already reviewed")
        if document["content_sha256"] != packet_document["source_sha256"]:
            raise VisualReviewError(f"{document['id']}: source hash drifted after review")
        if document["review"]["annotation_revision"] != packet_document["annotation_revision"]:
            raise VisualReviewError(f"{document['id']}: annotation revision drifted after review")
        current_cases = {f"{document['id']}/{case['id']}" for case in document["cases"]}
        packet_cases = {case["case_id"] for case in packet_document["cases"]}
        if current_cases != packet_cases:
            raise VisualReviewError(f"{document['id']}: case set drifted after review")
        document["review"] = {
            "status": "reviewed",
            "reviewers": [decision["reviewer"]],
            "reviewed_at": decision["reviewed_at"],
            "annotation_revision": document["review"]["annotation_revision"],
        }
    load_visual_registry_data(output)
    return output

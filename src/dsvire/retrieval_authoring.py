"""Leakage-safe authoring and independent-review seal for retrieval cycles."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from .pdf_backend import BACKEND_ID, PdfDocument
from .retrieval_preregistration import load_retrieval_preregistration
from .retrieval_source_seal import FROZEN_PLAN_DIGESTS, manifest_sha256

PACKET_VERSION = "dsvire.retrieval-authoring-packet.v1"
SUBMISSION_VERSION = "dsvire.retrieval-authoring-submission.v1"
REVIEW_VERSION = "dsvire.retrieval-authoring-review.v1"
SEAL_VERSION = "dsvire.retrieval-authoring-seal.v1"
REGION_TYPES = ("pinout", "table", "package")
NEGATIVE_KINDS = ("wrong_intent", "wrong_package", "wrong_variant", "wrong_view")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HUMAN = re.compile(r"github:[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_CASE_TOKEN = re.compile(r"(?:case|region|query)[-_]?[A-Za-z0-9]+", re.IGNORECASE)
_REQUIREMENTS = {
    "positive_region_types": list(REGION_TYPES),
    "hard_negative_kinds": list(NEGATIVE_KINDS),
    "minimum_hard_negatives_per_document": 4,
    "manual_queries_per_intent_per_document": 2,
    "annotation_review": "distinct independent human, blinded to all model scores",
    "query_review": "distinct independent human, blinded to all model scores",
    "prohibited": [
        "model-generated queries",
        "template-only queries",
        "labels or case IDs in query text",
        "score access before final seal",
    ],
}


class RetrievalAuthoringError(ValueError):
    """An authoring packet, submission, review, or seal violated the frozen contract."""


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _strict(value: Mapping[str, Any], keys: set[str], context: str) -> None:
    missing = keys - set(value)
    unknown = set(value) - keys
    if missing or unknown:
        raise RetrievalAuthoringError(
            f"{context} keys invalid: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalAuthoringError(f"{context} must be non-empty text")
    return value.strip()


def _digest(value: Any, context: str) -> str:
    digest = _text(value, context)
    if _SHA256.fullmatch(digest) is None:
        raise RetrievalAuthoringError(f"{context} must be lowercase SHA-256")
    return digest


def _human(value: Any, context: str) -> str:
    identity = _text(value, context)
    if _HUMAN.fullmatch(identity) is None:
        raise RetrievalAuthoringError(f"{context} must be a github:<human> identity")
    return identity


def _without_digest(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: child for name, child in value.items() if name != key}


def build_authoring_packet(
    plan: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    source_loader: Callable[[str], bytes],
) -> dict[str, Any]:
    """Bind exact sources and rendered pages without exposing splits or score data."""
    if not source_manifest.get("complete") or source_manifest.get("invalidations"):
        raise RetrievalAuthoringError("source manifest must be complete and uninvalidated")
    plan_id = _text(plan.get("plan_id"), "plan.plan_id")
    frozen_digest = FROZEN_PLAN_DIGESTS.get(plan_id)
    if frozen_digest is None:
        raise RetrievalAuthoringError("authoring packet requires an explicitly frozen plan")
    registered = load_retrieval_preregistration(plan, consumed_family_ids=set())
    if registered.content_sha256 != frozen_digest:
        raise RetrievalAuthoringError("pre-registration bytes differ from the frozen plan digest")
    if source_manifest.get("plan_id") != plan_id:
        raise RetrievalAuthoringError("source manifest plan does not match")
    if source_manifest.get("plan_sha256") != frozen_digest:
        raise RetrievalAuthoringError("source manifest does not bind the frozen plan digest")
    if source_manifest.get("manifest_sha256") != manifest_sha256(source_manifest):
        raise RetrievalAuthoringError("source manifest digest mismatch")
    families = plan.get("families")
    sources = source_manifest.get("sources")
    if not isinstance(families, list) or not isinstance(sources, list):
        raise RetrievalAuthoringError("plan families and manifest sources must be arrays")
    source_by_id = {str(source.get("id")): source for source in sources}
    if len(source_by_id) != len(sources):
        raise RetrievalAuthoringError("source manifest contains duplicate family IDs")
    documents: list[dict[str, Any]] = []
    for family in families:
        family_id = _text(family.get("id"), "family.id")
        source = source_by_id.get(family_id)
        if source is None or source.get("status") != "sealed":
            raise RetrievalAuthoringError(f"{family_id}: exact source is not sealed")
        source_sha256 = _digest(source.get("content_sha256"), f"{family_id}.source_sha256")
        source_bytes = source_loader(source_sha256)
        if hashlib.sha256(source_bytes).hexdigest() != source_sha256:
            raise RetrievalAuthoringError(f"{family_id}: source SHA-256 mismatch")
        pages: list[dict[str, Any]] = []
        with PdfDocument(source_bytes) as document:
            for index in range(document.page_count):
                with document.load_page(index) as page:
                    png = page.render_png((0.0, 0.0, page.rect.width, page.rect.height), dpi=96)
                    pages.append(
                        {
                            "page": index + 1,
                            "width_points": round(page.rect.width, 3),
                            "height_points": round(page.rect.height, 3),
                            "render_sha256": hashlib.sha256(png).hexdigest(),
                        }
                    )
        documents.append(
            {
                "id": family_id,
                "manufacturer": _text(family.get("manufacturer"), f"{family_id}.manufacturer"),
                "datasheet_identity": _text(
                    family.get("datasheet_identity"), f"{family_id}.datasheet_identity"
                ),
                "selected_mpn": _text(family.get("selected_mpn"), f"{family_id}.selected_mpn"),
                "selected_package": _text(
                    family.get("selected_package"), f"{family_id}.selected_package"
                ),
                "source_sha256": source_sha256,
                "pages": pages,
            }
        )
    if set(source_by_id) != {document["id"] for document in documents}:
        raise RetrievalAuthoringError("source manifest contains families outside the frozen plan")
    packet_payload = {
        "schema_version": PACKET_VERSION,
        "plan_id": plan_id,
        "plan_sha256": _digest(source_manifest.get("plan_sha256"), "manifest.plan_sha256"),
        "source_manifest_sha256": _digest(
            source_manifest.get("manifest_sha256"), "manifest.manifest_sha256"
        ),
        "renderer": BACKEND_ID,
        "requirements": _REQUIREMENTS,
        "documents": documents,
    }
    return {**packet_payload, "packet_sha256": canonical_sha256(packet_payload)}


def load_authoring_packet(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RetrievalAuthoringError("authoring packet must be an object")
    keys = {
        "schema_version",
        "plan_id",
        "plan_sha256",
        "source_manifest_sha256",
        "renderer",
        "requirements",
        "documents",
        "packet_sha256",
    }
    _strict(value, keys, "authoring packet")
    if value["schema_version"] != PACKET_VERSION:
        raise RetrievalAuthoringError("unsupported authoring packet schema")
    _text(value["plan_id"], "authoring packet.plan_id")
    _text(value["renderer"], "authoring packet.renderer")
    if value["requirements"] != _REQUIREMENTS:
        raise RetrievalAuthoringError("authoring packet requirements differ from frozen contract")
    _digest(value["plan_sha256"], "authoring packet.plan_sha256")
    _digest(value["source_manifest_sha256"], "authoring packet.source_manifest_sha256")
    packet_sha256 = _digest(value["packet_sha256"], "authoring packet.packet_sha256")
    if canonical_sha256(_without_digest(value, "packet_sha256")) != packet_sha256:
        raise RetrievalAuthoringError("authoring packet digest mismatch")
    documents = value["documents"]
    if not isinstance(documents, list) or len(documents) != 12:
        raise RetrievalAuthoringError("authoring packet must contain twelve documents")
    ids: set[str] = set()
    for document in documents:
        if not isinstance(document, Mapping):
            raise RetrievalAuthoringError("authoring packet document must be an object")
        _strict(
            document,
            {
                "id",
                "manufacturer",
                "datasheet_identity",
                "selected_mpn",
                "selected_package",
                "source_sha256",
                "pages",
            },
            "authoring packet document",
        )
        document_id = _text(document["id"], "authoring packet document.id")
        if document_id in ids:
            raise RetrievalAuthoringError("duplicate authoring packet document")
        ids.add(document_id)
        for field in ("manufacturer", "datasheet_identity", "selected_mpn", "selected_package"):
            _text(document[field], f"{document_id}.{field}")
        _digest(document["source_sha256"], f"{document_id}.source_sha256")
        pages = document["pages"]
        if not isinstance(pages, list) or not pages:
            raise RetrievalAuthoringError(f"{document_id}: pages must be non-empty")
        for expected, page in enumerate(pages, 1):
            if not isinstance(page, Mapping):
                raise RetrievalAuthoringError(f"{document_id}: invalid page")
            _strict(
                page,
                {"page", "width_points", "height_points", "render_sha256"},
                f"{document_id}.page",
            )
            if page["page"] != expected:
                raise RetrievalAuthoringError(f"{document_id}: pages must be contiguous")
            for dimension in ("width_points", "height_points"):
                if (
                    not isinstance(page[dimension], (int, float))
                    or isinstance(page[dimension], bool)
                    or page[dimension] <= 0
                ):
                    raise RetrievalAuthoringError(
                        f"{document_id}: page dimensions must be positive numbers"
                    )
            _digest(page["render_sha256"], f"{document_id}.page.render_sha256")
    encoded = json.dumps(value, sort_keys=True).casefold()
    for prohibited in ("split", "score", "threshold", "calibration", "evaluation"):
        if f'"{prohibited}"' in encoded:
            raise RetrievalAuthoringError(
                f"authoring packet exposes prohibited field: {prohibited}"
            )
    return dict(value)


def submission_template(packet: Mapping[str, Any]) -> dict[str, Any]:
    checked = load_authoring_packet(packet)
    return {
        "schema_version": SUBMISSION_VERSION,
        "packet_sha256": checked["packet_sha256"],
        "author": "github:REPLACE_WITH_HUMAN_AUTHOR",
        "manual_query_attestation": "REPLACE_WITH_EXPLICIT_HUMAN_ATTESTATION",
        "documents": [
            {"id": document["id"], "regions": [], "queries": []}
            for document in checked["documents"]
        ],
        "submission_sha256": "RECOMPUTED_BY_SEAL_COMMAND",
    }


def finalize_submission(value: Any, packet: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the canonical digest and then apply the complete semantic validator."""
    if not isinstance(value, Mapping):
        raise RetrievalAuthoringError("submission must be an object")
    payload = _without_digest(value, "submission_sha256")
    finalized = {**payload, "submission_sha256": canonical_sha256(payload)}
    return load_submission(finalized, packet)


def load_submission(value: Any, packet: Mapping[str, Any]) -> dict[str, Any]:
    checked_packet = load_authoring_packet(packet)
    if not isinstance(value, Mapping):
        raise RetrievalAuthoringError("submission must be an object")
    _strict(
        value,
        {
            "schema_version",
            "packet_sha256",
            "author",
            "manual_query_attestation",
            "documents",
            "submission_sha256",
        },
        "submission",
    )
    if value["schema_version"] != SUBMISSION_VERSION:
        raise RetrievalAuthoringError("unsupported submission schema")
    if value["packet_sha256"] != checked_packet["packet_sha256"]:
        raise RetrievalAuthoringError("submission packet digest mismatch")
    _human(value["author"], "submission.author")
    attestation = _text(value["manual_query_attestation"], "manual_query_attestation")
    if "human-authored" not in attestation.casefold() or "no model" not in attestation.casefold():
        raise RetrievalAuthoringError(
            "manual query attestation must state human authorship and no model use"
        )
    submission_sha256 = _digest(value["submission_sha256"], "submission.submission_sha256")
    if canonical_sha256(_without_digest(value, "submission_sha256")) != submission_sha256:
        raise RetrievalAuthoringError("submission digest mismatch")
    packet_documents = {document["id"]: document for document in checked_packet["documents"]}
    documents = value["documents"]
    if not isinstance(documents, list) or len(documents) != len(packet_documents):
        raise RetrievalAuthoringError("submission must cover every packet document")
    seen_documents: set[str] = set()
    all_query_texts: set[str] = set()
    for document in documents:
        if not isinstance(document, Mapping):
            raise RetrievalAuthoringError("submission document must be an object")
        _strict(document, {"id", "regions", "queries"}, "submission document")
        document_id = _text(document["id"], "submission document.id")
        if document_id not in packet_documents or document_id in seen_documents:
            raise RetrievalAuthoringError("submission document coverage is invalid")
        seen_documents.add(document_id)
        page_count = len(packet_documents[document_id]["pages"])
        regions = document["regions"]
        if not isinstance(regions, list) or len(regions) < 7:
            raise RetrievalAuthoringError(f"{document_id}: at least seven regions are required")
        region_ids: set[str] = set()
        region_kinds: dict[str, str] = {}
        region_intents: dict[str, str] = {}
        positives: set[str] = set()
        positive_count = 0
        negatives: set[str] = set()
        for region in regions:
            if not isinstance(region, Mapping):
                raise RetrievalAuthoringError(f"{document_id}: region must be an object")
            _strict(
                region,
                {"id", "kind", "intent", "page", "bbox_norm", "view", "note"},
                f"{document_id}.region",
            )
            region_id = _text(region["id"], f"{document_id}.region.id")
            if region_id in region_ids:
                raise RetrievalAuthoringError(f"{document_id}: duplicate region ID")
            region_ids.add(region_id)
            kind = _text(region["kind"], f"{document_id}.{region_id}.kind")
            intent = _text(region["intent"], f"{document_id}.{region_id}.intent")
            if intent not in REGION_TYPES:
                raise RetrievalAuthoringError(f"{document_id}: invalid region intent")
            if kind == "positive":
                positives.add(intent)
                positive_count += 1
            elif kind in NEGATIVE_KINDS:
                negatives.add(kind)
            else:
                raise RetrievalAuthoringError(f"{document_id}: invalid region kind")
            region_kinds[region_id] = kind
            region_intents[region_id] = intent
            if not isinstance(region["page"], int) or not 1 <= region["page"] <= page_count:
                raise RetrievalAuthoringError(f"{document_id}: region page outside packet")
            bbox = region["bbox_norm"]
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or not all(
                    isinstance(item, (int, float)) and not isinstance(item, bool) for item in bbox
                )
                or not 0 <= bbox[0] < bbox[2] <= 1
                or not 0 <= bbox[1] < bbox[3] <= 1
            ):
                raise RetrievalAuthoringError(f"{document_id}: invalid normalized bbox")
            _text(region["note"], f"{document_id}.{region_id}.note")
            if region["view"] not in {"top", "bottom", "not_applicable", "unknown"}:
                raise RetrievalAuthoringError(f"{document_id}: invalid region view")
        if positives != set(REGION_TYPES) or positive_count != 3:
            raise RetrievalAuthoringError(
                f"{document_id}: exactly all three positive intents required"
            )
        if negatives != set(NEGATIVE_KINDS):
            raise RetrievalAuthoringError(f"{document_id}: all four hard-negative kinds required")
        queries = document["queries"]
        if not isinstance(queries, list) or len(queries) != 6:
            raise RetrievalAuthoringError(f"{document_id}: exactly six manual queries required")
        intent_counts = dict.fromkeys(REGION_TYPES, 0)
        query_ids: set[str] = set()
        for query in queries:
            if not isinstance(query, Mapping):
                raise RetrievalAuthoringError(f"{document_id}: query must be an object")
            _strict(
                query,
                {"id", "intent", "text", "relevant_region_ids", "hard_negative_region_ids"},
                f"{document_id}.query",
            )
            intent = _text(query["intent"], f"{document_id}.query.intent")
            if intent not in intent_counts:
                raise RetrievalAuthoringError(f"{document_id}: invalid query intent")
            intent_counts[intent] += 1
            query_id = _text(query["id"], f"{document_id}.query.id")
            if query_id in query_ids:
                raise RetrievalAuthoringError(f"{document_id}: duplicate query ID")
            query_ids.add(query_id)
            text = _text(query["text"], f"{document_id}.query.text")
            normalized = " ".join(text.casefold().split())
            if normalized in all_query_texts:
                raise RetrievalAuthoringError("duplicate query text")
            all_query_texts.add(normalized)
            if (
                len(text.split()) < 4
                or _CASE_TOKEN.search(text)
                or any(
                    identifier.casefold() in normalized for identifier in region_ids | {query_id}
                )
            ):
                raise RetrievalAuthoringError(
                    f"{document_id}: query text looks templated or label-bearing"
                )
            relevant = query["relevant_region_ids"]
            negatives_for_query = query["hard_negative_region_ids"]
            if (
                not isinstance(relevant, list)
                or not relevant
                or not set(relevant) <= region_ids
                or any(
                    region_kinds[item] != "positive" or region_intents[item] != intent
                    for item in relevant
                )
            ):
                raise RetrievalAuthoringError(
                    f"{document_id}: relevant links must be positive and intent-matched"
                )
            if (
                not isinstance(negatives_for_query, list)
                or not negatives_for_query
                or not set(negatives_for_query) <= region_ids
                or any(region_kinds[item] == "positive" for item in negatives_for_query)
            ):
                raise RetrievalAuthoringError(
                    f"{document_id}: hard-negative links must reference negative regions"
                )
        if set(intent_counts.values()) != {2}:
            raise RetrievalAuthoringError(f"{document_id}: two queries per intent required")
    return dict(value)


def seal_submission(
    packet: Mapping[str, Any],
    submission: Mapping[str, Any],
    review: Mapping[str, Any],
    provenance_loader: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    checked_packet = load_authoring_packet(packet)
    checked_submission = load_submission(submission, checked_packet)
    if not isinstance(review, Mapping):
        raise RetrievalAuthoringError("review must be an object")
    _strict(
        review,
        {
            "schema_version",
            "packet_sha256",
            "submission_sha256",
            "author_attested_at",
            "author_attestation_url",
            "reviewer",
            "reviewed_at",
            "review_url",
        },
        "review",
    )
    if review["schema_version"] != REVIEW_VERSION:
        raise RetrievalAuthoringError("unsupported review schema")
    reviewer = _human(review["reviewer"], "review.reviewer")
    if reviewer == checked_submission["author"]:
        raise RetrievalAuthoringError(
            "independent reviewer must differ from annotation/query author"
        )
    if review["packet_sha256"] != checked_packet["packet_sha256"]:
        raise RetrievalAuthoringError("review packet digest mismatch")
    if review["submission_sha256"] != checked_submission["submission_sha256"]:
        raise RetrievalAuthoringError("review submission digest mismatch")
    author_provenance = provenance_loader(
        _text(review["author_attestation_url"], "review.author_attestation_url")
    )
    try:
        author_login = author_provenance["user"]["login"]
        author_state = author_provenance["state"]
        author_submitted_at = author_provenance["submitted_at"]
        author_body = author_provenance["body"] or ""
        author_url = author_provenance["html_url"]
    except (KeyError, TypeError) as exc:
        raise RetrievalAuthoringError("author provenance is incomplete") from exc
    author_marker = f"DSVIRE_AUTHORING_SUBMISSION_SHA256={checked_submission['submission_sha256']}"
    if (
        checked_submission["author"] != f"github:{author_login}"
        or author_state not in {"COMMENTED", "APPROVED"}
        or author_submitted_at != review["author_attested_at"]
        or author_url != review["author_attestation_url"]
        or author_marker not in author_body
        or "HUMAN_AUTHORED_NO_MODEL=TRUE" not in author_body
    ):
        raise RetrievalAuthoringError("author provenance does not bind human no-model authorship")
    provenance = provenance_loader(_text(review["review_url"], "review.review_url"))
    try:
        login = provenance["user"]["login"]
        state = provenance["state"]
        submitted_at = provenance["submitted_at"]
        body = provenance["body"] or ""
        html_url = provenance["html_url"]
    except (KeyError, TypeError) as exc:
        raise RetrievalAuthoringError("review provenance is incomplete") from exc
    if reviewer != f"github:{login}" or state != "APPROVED":
        raise RetrievalAuthoringError(
            "review provenance is not an approval by the declared reviewer"
        )
    if submitted_at != review["reviewed_at"] or html_url != review["review_url"]:
        raise RetrievalAuthoringError("review provenance timestamp or URL mismatch")
    markers = (
        f"DSVIRE_AUTHORING_PACKET_SHA256={checked_packet['packet_sha256']}",
        f"DSVIRE_AUTHORING_SUBMISSION_SHA256={checked_submission['submission_sha256']}",
        "DSVIRE_INDEPENDENT_HUMAN_REVIEW=TRUE",
    )
    if not all(marker in body for marker in markers):
        raise RetrievalAuthoringError("review approval does not bind packet and submission digests")
    payload = {
        "schema_version": SEAL_VERSION,
        "plan_id": checked_packet["plan_id"],
        "plan_sha256": checked_packet["plan_sha256"],
        "source_manifest_sha256": checked_packet["source_manifest_sha256"],
        "packet_sha256": checked_packet["packet_sha256"],
        "submission_sha256": checked_submission["submission_sha256"],
        "author": checked_submission["author"],
        "author_attested_at": review["author_attested_at"],
        "author_attestation_url": review["author_attestation_url"],
        "reviewer": reviewer,
        "reviewed_at": review["reviewed_at"],
        "review_url": review["review_url"],
        "documents": len(checked_packet["documents"]),
        "regions": sum(len(document["regions"]) for document in checked_submission["documents"]),
        "queries": sum(len(document["queries"]) for document in checked_submission["documents"]),
        "score_access_authorized": True,
    }
    return {**payload, "seal_sha256": canonical_sha256(payload)}


def load_authoring_seal(
    value: Any,
    packet: Mapping[str, Any],
    submission: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the immutable authorization boundary before any score access."""
    checked_packet = load_authoring_packet(packet)
    checked_submission = load_submission(submission, checked_packet)
    if not isinstance(value, Mapping):
        raise RetrievalAuthoringError("authoring seal must be an object")
    keys = {
        "schema_version",
        "plan_id",
        "plan_sha256",
        "source_manifest_sha256",
        "packet_sha256",
        "submission_sha256",
        "author",
        "author_attested_at",
        "author_attestation_url",
        "reviewer",
        "reviewed_at",
        "review_url",
        "documents",
        "regions",
        "queries",
        "score_access_authorized",
        "seal_sha256",
    }
    _strict(value, keys, "authoring seal")
    if value["schema_version"] != SEAL_VERSION:
        raise RetrievalAuthoringError("unsupported authoring seal schema")
    bindings = {
        "plan_id": checked_packet["plan_id"],
        "plan_sha256": checked_packet["plan_sha256"],
        "source_manifest_sha256": checked_packet["source_manifest_sha256"],
        "packet_sha256": checked_packet["packet_sha256"],
        "submission_sha256": checked_submission["submission_sha256"],
        "author": checked_submission["author"],
        "documents": len(checked_packet["documents"]),
        "regions": sum(len(item["regions"]) for item in checked_submission["documents"]),
        "queries": sum(len(item["queries"]) for item in checked_submission["documents"]),
        "score_access_authorized": True,
    }
    for field, expected in bindings.items():
        if value[field] != expected:
            raise RetrievalAuthoringError(f"authoring seal {field} binding mismatch")
    reviewer = _human(value["reviewer"], "authoring seal.reviewer")
    if reviewer == checked_submission["author"]:
        raise RetrievalAuthoringError("authoring seal reviewer is not independent")
    for field in (
        "author_attested_at",
        "author_attestation_url",
        "reviewed_at",
        "review_url",
    ):
        _text(value[field], f"authoring seal.{field}")
    seal_sha256 = _digest(value["seal_sha256"], "authoring seal.seal_sha256")
    if canonical_sha256(_without_digest(value, "seal_sha256")) != seal_sha256:
        raise RetrievalAuthoringError("authoring seal digest mismatch")
    return dict(value)

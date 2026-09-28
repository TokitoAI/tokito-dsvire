"""Export a sealed authoring submission into visual and query registries.

Coverage intents outside pinout/table/package stay out of the visual registry.
Identity negatives are stored as package regions so the EGVV label contract holds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .corpus_coverage import load_query_registry
from .retrieval_authoring import (
    REGION_TYPES,
    RetrievalAuthoringError,
    load_authoring_packet,
    load_authoring_seal,
    load_submission,
)
from .visual_registry import REGISTRY_VERSION, load_visual_registry_data

KIND_TO_LABEL = {
    "positive": "positive",
    "wrong_intent": "wrong_figure",
    "wrong_package": "wrong_package",
    "wrong_variant": "wrong_variant",
    "wrong_view": "wrong_view",
}
OPPOSITE_VIEW = {"top": "bottom", "bottom": "top"}


def _family_index(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    families = plan.get("families")
    if not isinstance(families, list):
        raise RetrievalAuthoringError("plan families must be an array")
    return {str(family["id"]): family for family in families}


def _source_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise RetrievalAuthoringError("source manifest sources must be an array")
    return {str(source["id"]): source for source in sources}


def _packet_index(packet: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(document["id"]): document for document in packet["documents"]}


def _other_package(package: str) -> str:
    return "SOIC-8" if package.casefold() != "soic-8" else "TSSOP-8"


def _other_mpn(mpn: str) -> str:
    return f"{mpn}-X"


def _claimed_identity(kind: str, identity: dict[str, str]) -> dict[str, str]:
    if kind == "wrong_package":
        return {**identity, "package": _other_package(identity["package"])}
    if kind == "wrong_variant":
        return {**identity, "mpn": _other_mpn(identity["mpn"])}
    return dict(identity)


def _region_type(kind: str, intent: str) -> str | None:
    if kind in {"wrong_package", "wrong_variant"}:
        return "package"
    if intent in REGION_TYPES:
        return intent
    return None


def _oppose_wrong_views(cases: list[dict[str, Any]]) -> None:
    positives = [
        (case["region_type"], case["view"]) for case in cases if case["label"] == "positive"
    ]
    for case in cases:
        if case["label"] != "wrong_view":
            continue
        same_type_positive = next(
            (
                view
                for region_type, view in positives
                if region_type == case["region_type"] and view in OPPOSITE_VIEW
            ),
            None,
        )
        if same_type_positive is None:
            fallback = next(
                ((region_type, view) for region_type, view in positives if view in OPPOSITE_VIEW),
                None,
            )
            if fallback is None:
                case["label"] = "wrong_figure"
                continue
            case["region_type"], same_type_positive = fallback
        if case["view"] not in OPPOSITE_VIEW or case["view"] == same_type_positive:
            case["view"] = OPPOSITE_VIEW[same_type_positive]


def _export_document(
    submission_document: Mapping[str, Any],
    family: Mapping[str, Any],
    packet_document: Mapping[str, Any],
    source: Mapping[str, Any],
    seal: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    document_id = str(submission_document["id"])
    identity = {
        "manufacturer": str(packet_document["manufacturer"]),
        "mpn": str(packet_document["selected_mpn"]),
        "package": str(packet_document["selected_package"]),
    }
    cases: list[dict[str, Any]] = []
    region_map: dict[str, str] = {}
    for region in submission_document["regions"]:
        kind = str(region["kind"])
        intent = str(region["intent"])
        region_type = _region_type(kind, intent)
        if region_type is None:
            continue
        label = KIND_TO_LABEL[kind]
        case_id = str(region["id"])
        cases.append(
            {
                "id": case_id,
                "label": label,
                "region_type": region_type,
                "page": region["page"],
                "bbox_norm": list(region["bbox_norm"]),
                "view": region["view"],
                "claimed_identity": _claimed_identity(kind, identity),
                "rationale": str(region["note"]),
            }
        )
        region_map[case_id] = f"{document_id}/{case_id}"
    if not cases:
        raise RetrievalAuthoringError(f"{document_id}: no visual-registry cases exported")
    _oppose_wrong_views(cases)
    manufacturer = identity["manufacturer"]
    document = {
        "id": document_id,
        "document_group": document_id,
        "split": str(family["split"]),
        "category": str(family["category"]),
        "source": {
            "url": str(family["official_source_url"]),
            "revision": str(family["datasheet_identity"]),
        },
        "content_sha256": str(source["content_sha256"]),
        "redistribution": "download_only",
        "license_note": (
            f"Official {manufacturer} datasheet; URL, hash, and annotations only; "
            "PDF bytes are not redistributed."
        ),
        "identity": identity,
        "review": {
            "status": "reviewed",
            "reviewers": [str(seal["reviewer"])],
            "reviewed_at": str(seal["reviewed_at"]),
            "annotation_revision": str(seal["seal_sha256"]),
        },
        "cases": cases,
    }
    return document, region_map


def export_sealed_cycle_eval_artifacts(
    plan: Mapping[str, Any],
    packet: Mapping[str, Any],
    submission: Mapping[str, Any],
    seal: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Build source-free visual/query registries and a matching split plan."""
    checked_packet = load_authoring_packet(packet)
    checked_submission = load_submission(submission, checked_packet)
    checked_seal = load_authoring_seal(seal, checked_packet, checked_submission)
    if not checked_seal["score_access_authorized"]:
        raise RetrievalAuthoringError("score access is not authorized")
    families = _family_index(plan)
    sources = _source_index(source_manifest)
    packets = _packet_index(checked_packet)
    visual_documents: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    region_maps: dict[str, dict[str, str]] = {}
    for submission_document in checked_submission["documents"]:
        document_id = str(submission_document["id"])
        document, region_map = _export_document(
            submission_document,
            families[document_id],
            packets[document_id],
            sources[document_id],
            checked_seal,
        )
        visual_documents.append(document)
        region_maps[document_id] = region_map
        mapped_cases = {case["id"] for case in document["cases"]}
        for query in submission_document["queries"]:
            relevant = [
                region_map[region_id]
                for region_id in query["relevant_region_ids"]
                if region_id in mapped_cases
            ]
            if not relevant:
                raise RetrievalAuthoringError(
                    f"{document_id}/{query['id']}: relevant regions were not exported"
                )
            hard_negatives = [
                region_map[region_id]
                for region_id in query["hard_negative_region_ids"]
                if region_id in mapped_cases
            ]
            if not hard_negatives:
                hard_negatives = [
                    region_map[case["id"]]
                    for case in document["cases"]
                    if case["id"] not in set(query["relevant_region_ids"])
                    and case["label"] != "positive"
                ]
            if not hard_negatives:
                raise RetrievalAuthoringError(
                    f"{document_id}/{query['id']}: no hard negatives exported"
                )
            queries.append(
                {
                    "id": f"{document_id}/{query['id']}",
                    "document_group": document_id,
                    "split": document["split"],
                    "query_text": query["text"],
                    "query_type": query["intent"],
                    "relevance_judgments": [
                        {"case_id": case_id, "grade": 2} for case_id in relevant
                    ],
                    "hard_negative_case_ids": hard_negatives,
                    "provenance": {
                        "method": "manual",
                        "generator": str(checked_submission["author"]),
                        "independently_reviewed": True,
                    },
                }
            )
    visual_raw = {"schema_version": REGISTRY_VERSION, "documents": visual_documents}
    query_raw = {"schema_version": "dsvire.query-registry.v2", "queries": queries}
    visual = load_visual_registry_data(visual_raw)
    load_query_registry(query_raw, visual)
    split_plan = {
        "schema_version": "dsvire.visual-split-plan.v1",
        "created_at": str(checked_seal["reviewed_at"]),
        "assignment_method": (
            "Copied from the frozen cycle plan before scoring; calibration and "
            "evaluation family membership is unchanged."
        ),
        "families": [
            {
                "id": document["id"],
                "split": document["split"],
                "category": document["category"],
                "source_url": document["source"]["url"],
                "content_sha256": document["content_sha256"],
            }
            for document in visual_documents
        ],
    }
    return {
        "visual_registry": visual_raw,
        "query_registry": query_raw,
        "split_plan": split_plan,
        "visual_registry_sha256": visual.content_sha256,
        "plan_id": checked_packet["plan_id"],
        "seal_sha256": checked_seal["seal_sha256"],
        "submission_sha256": checked_submission["submission_sha256"],
    }

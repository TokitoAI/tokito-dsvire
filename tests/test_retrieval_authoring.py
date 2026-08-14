from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from dsvire.pdf_fixtures import text_pdf
from dsvire.retrieval_authoring import (
    PACKET_VERSION,
    REVIEW_VERSION,
    SUBMISSION_VERSION,
    RetrievalAuthoringError,
    canonical_sha256,
    finalize_submission,
    load_authoring_packet,
    load_authoring_seal,
    load_submission,
    seal_submission,
)

ROOT = Path(__file__).resolve().parents[1]


def _packet() -> dict[str, object]:
    documents = []
    for index in range(12):
        documents.append(
            {
                "id": f"document-{index}",
                "manufacturer": "Vendor",
                "datasheet_identity": f"Document {index}",
                "selected_mpn": f"PART-{index}",
                "selected_package": "QFN-16",
                "source_sha256": f"{index + 1:064x}",
                "pages": [
                    {
                        "page": 1,
                        "width_points": 612.0,
                        "height_points": 792.0,
                        "render_sha256": f"{index + 20:064x}",
                    }
                ],
            }
        )
    payload = {
        "schema_version": PACKET_VERSION,
        "plan_id": "plan-v1",
        "plan_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "renderer": "pdfium-test",
        "requirements": {
            "positive_region_types": ["pinout", "table", "package"],
            "hard_negative_kinds": [
                "wrong_intent",
                "wrong_package",
                "wrong_variant",
                "wrong_view",
            ],
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
        },
        "documents": documents,
    }
    return {**payload, "packet_sha256": canonical_sha256(payload)}


def _submission(packet: dict[str, object]) -> dict[str, object]:
    documents = []
    for document in packet["documents"]:
        document_id = document["id"]
        regions = [
            {
                "id": f"positive-{intent}",
                "kind": "positive",
                "intent": intent,
                "page": 1,
                "bbox_norm": [0.1, 0.1, 0.4, 0.4],
                "view": "not_applicable",
                "note": f"Human-inspected {intent} evidence.",
            }
            for intent in ("pinout", "table", "package")
        ]
        regions.extend(
            {
                "id": f"negative-{kind}",
                "kind": kind,
                "intent": "pinout",
                "page": 1,
                "bbox_norm": [0.5, 0.5, 0.9, 0.9],
                "view": "not_applicable",
                "note": f"Human-inspected {kind} adversary.",
            }
            for kind in ("wrong_intent", "wrong_package", "wrong_variant", "wrong_view")
        )
        queries = []
        for intent in ("pinout", "table", "package"):
            for number in (1, 2):
                queries.append(
                    {
                        "id": f"q-{intent}-{number}",
                        "intent": intent,
                        "text": f"Where does {document_id} show its {intent} details for design use number {number}?",
                        "relevant_region_ids": [f"positive-{intent}"],
                        "hard_negative_region_ids": ["negative-wrong_intent"],
                    }
                )
        documents.append({"id": document_id, "regions": regions, "queries": queries})
    payload = {
        "schema_version": SUBMISSION_VERSION,
        "packet_sha256": packet["packet_sha256"],
        "author": "github:human-author",
        "manual_query_attestation": "These queries are human-authored and no model was used.",
        "documents": documents,
    }
    return {**payload, "submission_sha256": canonical_sha256(payload)}


def _review(packet: dict[str, object], submission: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": REVIEW_VERSION,
        "packet_sha256": packet["packet_sha256"],
        "submission_sha256": submission["submission_sha256"],
        "author_attested_at": "2026-08-13T00:00:00Z",
        "author_attestation_url": "https://github.com/TokitoAI/tokito-dsvire/pull/1#pullrequestreview-1",
        "reviewer": "github:human-reviewer",
        "reviewed_at": "2026-08-13T01:00:00Z",
        "review_url": "https://github.com/TokitoAI/tokito-dsvire/pull/1#pullrequestreview-2",
    }


def _provenance(url: str) -> dict[str, object]:
    if url.endswith("-1"):
        return {
            "user": {"login": "human-author"},
            "state": "COMMENTED",
            "submitted_at": "2026-08-13T00:00:00Z",
            "html_url": url,
            "body": "HUMAN_AUTHORED_NO_MODEL=TRUE\nDSVIRE_AUTHORING_SUBMISSION_SHA256="
            + _submission(_packet())["submission_sha256"],
        }
    packet = _packet()
    submission = _submission(packet)
    return {
        "user": {"login": "human-reviewer"},
        "state": "APPROVED",
        "submitted_at": "2026-08-13T01:00:00Z",
        "html_url": url,
        "body": (
            "DSVIRE_INDEPENDENT_HUMAN_REVIEW=TRUE\n"
            f"DSVIRE_AUTHORING_PACKET_SHA256={packet['packet_sha256']}\n"
            f"DSVIRE_AUTHORING_SUBMISSION_SHA256={submission['submission_sha256']}"
        ),
    }


def _redigest_submission(submission: dict[str, object]) -> None:
    submission["submission_sha256"] = canonical_sha256(
        {key: value for key, value in submission.items() if key != "submission_sha256"}
    )


def test_complete_human_authored_independently_reviewed_submission_seals() -> None:
    packet = _packet()
    submission = _submission(packet)
    result = seal_submission(packet, submission, _review(packet, submission), _provenance)
    assert result["documents"] == 12
    assert result["regions"] == 84
    assert result["queries"] == 72
    assert result["score_access_authorized"] is True
    assert load_authoring_seal(result, packet, submission) == result


def test_finalize_submission_replaces_placeholder_and_validates() -> None:
    packet = _packet()
    submission = _submission(packet)
    submission["submission_sha256"] = "RECOMPUTED_BY_SEAL_COMMAND"
    assert finalize_submission(submission, packet) == _submission(packet)


def test_committed_packet_is_schema_valid_source_free_and_bound() -> None:
    packet = json.loads(
        (ROOT / "evaluation/retrieval_cycle_v4_authoring_packet.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "scripts/schema/retrieval_authoring_packet_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(packet)
    assert load_authoring_packet(packet) == packet
    assert packet["plan_sha256"] == (
        "cd7b1bd89d0e3d382eb7ea0af97107ca6931b3cd49a34964e18e4cef9dbb8acb"
    )
    assert packet["source_manifest_sha256"] == (
        "d6398ed9ea4ea5da7f8b726e030d2f77c94979705856c235d3aca8f8973fb9c6"
    )
    assert sum(len(document["pages"]) for document in packet["documents"]) == 587


def test_cycle_v4_human_handoff_runbook_binds_current_packet_and_review_markers() -> None:
    runbook = (ROOT / "evaluation/README.md").read_text(encoding="utf-8")
    packet = json.loads(
        (ROOT / "evaluation/retrieval_cycle_v4_authoring_packet.json").read_text(encoding="utf-8")
    )
    required = (
        f"DSVIRE_SOURCE_MANIFEST_SHA256={packet['source_manifest_sha256']}",
        f"DSVIRE_AUTHORING_PACKET_SHA256={packet['packet_sha256']}",
        "HUMAN_AUTHORED_NO_MODEL=TRUE",
        "DSVIRE_INDEPENDENT_HUMAN_REVIEW=TRUE",
        "finalize-submission",
        "validate-seal",
        "#pullrequestreview-<id>",
        "must be a different GitHub login",
        "does not enable publication",
    )
    for text in required:
        assert text in runbook


def test_all_authoring_schemas_are_valid() -> None:
    for path in sorted((ROOT / "scripts/schema").glob("retrieval_authoring_*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)


def test_completed_authoring_artifacts_match_their_formal_schemas() -> None:
    packet = _packet()
    submission = _submission(packet)
    review = _review(packet, submission)
    seal = seal_submission(packet, submission, review, _provenance)
    values = {
        "retrieval_authoring_packet_v1.schema.json": packet,
        "retrieval_authoring_submission_v1.schema.json": submission,
        "retrieval_authoring_review_v1.schema.json": review,
        "retrieval_authoring_seal_v1.schema.json": seal,
    }
    for name, value in values.items():
        schema = json.loads((ROOT / "scripts/schema" / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(value)


def test_authoring_seal_detects_post_review_mutation() -> None:
    packet = _packet()
    submission = _submission(packet)
    seal = seal_submission(packet, submission, _review(packet, submission), _provenance)
    seal["queries"] = 71
    with pytest.raises(RetrievalAuthoringError, match="queries binding mismatch"):
        load_authoring_seal(seal, packet, submission)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("score", "unknown"),
        ("packet_digest", "digest mismatch"),
        ("missing_document", "cover every"),
        ("missing_negative", "seven regions"),
        ("duplicate_query", "duplicate query text"),
        ("label_text", "templated or label-bearing"),
        ("wrong_relevant", "positive and intent-matched"),
        ("same_reviewer", "must differ"),
    ],
)
def test_authoring_boundary_fails_closed(mutation: str, message: str) -> None:
    packet = _packet()
    submission = _submission(packet)
    review = _review(packet, submission)
    if mutation == "score":
        packet["score"] = 0.9
        packet["packet_sha256"] = canonical_sha256(
            {key: value for key, value in packet.items() if key != "packet_sha256"}
        )
        with pytest.raises(RetrievalAuthoringError, match=message):
            load_authoring_packet(packet)
        return
    if mutation == "packet_digest":
        packet["documents"][0]["pages"][0]["render_sha256"] = "f" * 64
        with pytest.raises(RetrievalAuthoringError, match=message):
            load_authoring_packet(packet)
        return
    if mutation == "missing_document":
        submission["documents"].pop()
    elif mutation == "missing_negative":
        submission["documents"][0]["regions"].pop()
    elif mutation == "duplicate_query":
        submission["documents"][0]["queries"][1]["text"] = submission["documents"][0]["queries"][0][
            "text"
        ]
    elif mutation == "label_text":
        submission["documents"][0]["queries"][0]["text"] = (
            "Please find positive-pinout region case-1"
        )
    elif mutation == "wrong_relevant":
        submission["documents"][0]["queries"][0]["relevant_region_ids"] = ["negative-wrong_intent"]
    else:
        review["reviewer"] = submission["author"]
    _redigest_submission(submission)
    review["submission_sha256"] = submission["submission_sha256"]
    with pytest.raises(RetrievalAuthoringError, match=message):
        if mutation == "same_reviewer":
            seal_submission(packet, submission, review, _provenance)
        else:
            load_submission(submission, packet)


def test_fixture_import_remains_available_for_packet_builder_tests() -> None:
    assert text_pdf("packet fixture").startswith(b"%PDF")

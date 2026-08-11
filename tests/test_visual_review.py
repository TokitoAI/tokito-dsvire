from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dsvire.visual_adapters import AdapterError
from dsvire.visual_registry import VisualRegistry, load_visual_registry_data
from dsvire.visual_review import (
    VisualReviewError,
    apply_review_decision,
    build_review_packet,
    fetch_github_review_provenance,
    load_review_decision_data,
    load_review_packet_data,
    render_review_sheet,
    review_sheet_filename,
)


def _fixture() -> tuple[bytes, dict[str, object], VisualRegistry]:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "ACME A-1 SOIC-8 Pin Configuration Top View Pin Functions")
    payload = document.tobytes()
    document.close()
    identity = {"manufacturer": "ACME", "mpn": "A-1", "package": "SOIC-8"}

    def case(
        case_id: str,
        label: str,
        region: str,
        claimed: dict[str, str] | None = None,
        view: str = "not_applicable",
    ) -> dict[str, object]:
        return {
            "id": case_id,
            "label": label,
            "region_type": region,
            "page": 1,
            "bbox_norm": [0.0, 0.0, 1.0, 1.0],
            "view": view,
            "claimed_identity": claimed or identity,
            "rationale": "Synthetic review fixture.",
        }

    registry_data: dict[str, object] = {
        "schema_version": "dsvire.visual-eval-registry.v1",
        "documents": [
            {
                "id": "../acme/a-1",
                "document_group": "acme-a",
                "split": "development",
                "category": "test",
                "source": {"url": "https://example.invalid/a.pdf", "revision": "test"},
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "redistribution": "redistributable",
                "license_note": "Synthetic.",
                "identity": identity,
                "review": {
                    "status": "unreviewed",
                    "reviewers": [],
                    "reviewed_at": None,
                    "annotation_revision": "fixture@1",
                },
                "cases": [
                    case("pin", "positive", "pinout", view="top"),
                    case("table", "positive", "table"),
                    case("package", "positive", "package"),
                    case("wrong-view", "wrong_view", "pinout", view="bottom"),
                ],
            }
        ],
    }
    return payload, registry_data, load_visual_registry_data(registry_data)


def _decision(packet: dict[str, object], outcome: str = "accepted") -> dict[str, object]:
    return {
        "schema_version": "dsvire.visual-review-decision.v1",
        "packet_sha256": packet["packet_sha256"],
        "registry_sha256": packet["registry_sha256"],
        "reviewer": "github:independent-reviewer",
        "reviewed_at": "2026-08-12T04:00:00+05:30",
        "review_url": "https://github.com/TokitoAI/tokito-dsvire/pull/999#pullrequestreview-1",
        "decisions": [
            {
                "case_id": case["case_id"],
                "outcome": outcome,
                "note": "Incorrect crop." if outcome == "rejected" else "",
            }
            for document in packet["documents"]
            for case in document["cases"]
        ],
    }


def _approved_review(decision: dict[str, object]) -> dict[str, object]:
    return {
        "user": {"login": "independent-reviewer"},
        "state": "APPROVED",
        "submitted_at": "2026-08-11T22:30:00Z",
        "body": f"DSVIRE_REVIEW_PACKET_SHA256={decision['packet_sha256']}",
        "html_url": decision["review_url"],
    }


def test_review_sheet_is_png_and_labels_every_case() -> None:
    image_module = pytest.importorskip("PIL.Image")
    payload, _data, registry = _fixture()
    rendered = render_review_sheet(payload, registry.documents[0])
    with image_module.open(BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == (1880, 1400)


def test_review_sheet_rejects_unpinned_bytes() -> None:
    _payload, _data, registry = _fixture()
    with pytest.raises(AdapterError, match="SHA-256 mismatch"):
        render_review_sheet(b"not the pinned PDF", registry.documents[0])


def test_review_sheet_filename_cannot_escape_output_directory() -> None:
    filename = review_sheet_filename("../../sensitive\\name")
    assert "/" not in filename and "\\" not in filename and ".." not in filename
    assert filename.endswith(".png")


def test_review_packet_is_deterministic_and_binds_rendered_crop_bytes() -> None:
    payload, _data, registry = _fixture()
    first = build_review_packet(registry, lambda _document: payload)
    second = build_review_packet(registry, lambda _document: payload)

    assert first == second
    assert load_review_packet_data(first) == first
    assert len(first["packet_sha256"]) == 64
    assert all(
        len(case["crop_sha256"]) == 64
        for document in first["documents"]
        for case in document["cases"]
    )
    root = Path(__file__).parents[1]
    schema = json.loads((root / "scripts/schema/visual_review_packet_v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first)


def test_review_packet_rejects_tampering_and_unknown_selection() -> None:
    payload, _data, registry = _fixture()
    packet = build_review_packet(registry, lambda _document: payload)
    packet["documents"][0]["cases"][0]["page"] = 2
    with pytest.raises(VisualReviewError, match="digest mismatch"):
        load_review_packet_data(packet)
    with pytest.raises(VisualReviewError, match="unknown review document"):
        build_review_packet(registry, lambda _document: payload, document_ids={"missing"})


def test_complete_named_human_review_applies_to_exact_registry_revision() -> None:
    payload, registry_data, registry = _fixture()
    packet = build_review_packet(registry, lambda _document: payload)
    decision = _decision(packet)

    assert load_review_decision_data(decision, packet) == decision
    root = Path(__file__).parents[1]
    schema = json.loads((root / "scripts/schema/visual_review_decision_v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decision)
    output = apply_review_decision(
        registry_data,
        packet,
        decision,
        provenance_loader=lambda _url: _approved_review(decision),
    )
    review = output["documents"][0]["review"]
    assert review == {
        "status": "reviewed",
        "reviewers": ["github:independent-reviewer"],
        "reviewed_at": "2026-08-12T04:00:00+05:30",
        "annotation_revision": "fixture@1",
    }


def test_partial_rejected_or_drifted_review_cannot_apply() -> None:
    payload, registry_data, registry = _fixture()
    packet = build_review_packet(registry, lambda _document: payload)
    partial = _decision(packet)
    partial["decisions"].pop()
    with pytest.raises(VisualReviewError, match="incomplete"):
        load_review_decision_data(partial, packet)

    rejected = _decision(packet, "rejected")
    with pytest.raises(VisualReviewError, match="containing rejections"):
        apply_review_decision(
            registry_data,
            packet,
            rejected,
            provenance_loader=lambda _url: _approved_review(rejected),
        )

    drifted = json.loads(json.dumps(registry_data))
    drifted["documents"][0]["review"]["annotation_revision"] = "fixture@2"
    with pytest.raises(VisualReviewError, match="current registry does not match"):
        decision = _decision(packet)
        apply_review_decision(
            drifted,
            packet,
            decision,
            provenance_loader=lambda _url: _approved_review(decision),
        )


def test_review_application_rejects_unbound_or_mismatched_github_approval() -> None:
    payload, registry_data, registry = _fixture()
    packet = build_review_packet(registry, lambda _document: payload)
    decision = _decision(packet)
    provenance = _approved_review(decision)
    provenance["body"] = "approved without a packet binding"
    with pytest.raises(VisualReviewError, match="does not bind"):
        apply_review_decision(
            registry_data,
            packet,
            decision,
            provenance_loader=lambda _url: provenance,
        )

    provenance = _approved_review(decision)
    provenance["user"]["login"] = "someone-else"
    with pytest.raises(VisualReviewError, match="author does not match"):
        apply_review_decision(
            registry_data,
            packet,
            decision,
            provenance_loader=lambda _url: provenance,
        )


def test_github_review_fetch_rejects_non_tokito_review_url_without_network() -> None:
    with pytest.raises(VisualReviewError, match="TokitoAI pull-request review"):
        fetch_github_review_provenance("https://example.invalid/review")


def test_github_review_fetch_is_bounded_and_uses_token_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_url = "https://github.com/TokitoAI/tokito-dsvire/pull/999#pullrequestreview-123"
    expected_api = "https://api.github.com/repos/TokitoAI/tokito-dsvire/pulls/999/reviews/123"
    seen = {}

    class Response:
        def __init__(self) -> None:
            self.headers = {"Content-Length": "18"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self) -> str:
            return expected_api

        def read(self, limit: int) -> bytes:
            assert limit == 1_000_001
            return b'{"state":"APPROVED"}'

    def open_request(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr("dsvire.visual_review.urllib.request.urlopen", open_request)
    result = fetch_github_review_provenance(review_url, "secret-token")

    assert result == {"state": "APPROVED"}
    assert seen == {
        "url": expected_api,
        "authorization": "Bearer secret-token",
        "timeout": 15,
    }

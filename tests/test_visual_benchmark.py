from __future__ import annotations

from dataclasses import dataclass

import pytest

from dsvire.visual_adapters import AdapterMetadata
from dsvire.visual_benchmark import RESULT_VERSION, benchmark_registry
from dsvire.visual_registry import load_visual_registry_data


def _registry() -> dict:
    identity = {"manufacturer": "Acme", "mpn": "A-1", "package": "SOIC-8"}

    def case(
        case_id: str,
        label: str,
        region_type: str,
        *,
        claimed_identity: dict[str, str] | None = None,
        view: str = "not_applicable",
    ) -> dict:
        return {
            "id": case_id,
            "label": label,
            "region_type": region_type,
            "page": 1,
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "view": view,
            "claimed_identity": identity if claimed_identity is None else claimed_identity,
            "rationale": "Synthetic annotation.",
        }

    return {
        "schema_version": "dsvire.visual-eval-registry.v1",
        "documents": [
            {
                "id": "acme-a1",
                "document_group": "acme-a-family",
                "split": "development",
                "category": "regulator",
                "source": {"url": "https://example.invalid/a1.pdf", "revision": "1"},
                "content_sha256": "a" * 64,
                "redistribution": "redistributable",
                "license_note": "Synthetic fixture.",
                "identity": identity,
                "review": {
                    "status": "unreviewed",
                    "reviewers": [],
                    "reviewed_at": None,
                    "annotation_revision": "fixture@1",
                },
                "cases": [
                    case("pinout", "positive", "pinout", view="top"),
                    case("table", "positive", "table"),
                    case("package", "positive", "package"),
                    case("wrong-view", "wrong_view", "pinout", view="bottom"),
                    case(
                        "wrong-package",
                        "wrong_package",
                        "package",
                        claimed_identity={**identity, "package": "TSSOP-8"},
                    ),
                ],
            }
        ],
    }


@dataclass(frozen=True)
class _Adapter:
    metadata = AdapterMetadata(
        "fixture-adapter@1",
        "b" * 64,
        None,
        "fixture-preprocessing@1",
        "similarity",
    )

    def score(self, _document: object, _case: object) -> float:
        raise AssertionError("score_document is replaced by the benchmark boundary fixture")


def test_benchmark_binds_registry_labels_and_has_deterministic_score_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_visual_registry_data(_registry())

    def fake_score(_adapter: object, payload: bytes, document: object) -> dict[str, float]:
        assert payload == b"hash-checked-upstream"
        return {
            f"{document.document_id}/{case.case_id}": round(0.1 * (index + 1), 6)
            for index, case in enumerate(document.cases)
        }

    monkeypatch.setattr("dsvire.visual_benchmark.score_document", fake_score)
    first = benchmark_registry(registry, lambda _document: b"hash-checked-upstream", _Adapter())
    second = benchmark_registry(registry, lambda _document: b"hash-checked-upstream", _Adapter())

    assert first["schema_version"] == RESULT_VERSION
    assert first["score_sha256"] == second["score_sha256"]
    assert first["registry_sha256"] == registry.content_sha256
    assert first["eligible_for_policy_fitting"] is False
    assert first["summary"]["reviewed_calibration_documents"] == 0
    assert first["summary"]["reviewed_evaluation_documents"] == 0
    assert first["summary"]["external_cost_usd"] == 0.0
    assert first["summary"]["peak_rss_bytes"] > 0
    assert first["summary"]["labels"] == {"positive": 3, "wrong_package": 1, "wrong_view": 1}
    assert [entry["label"] for entry in first["documents"][0]["scores"]] == [
        case.label for case in registry.documents[0].cases
    ]

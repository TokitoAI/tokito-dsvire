from __future__ import annotations

import hashlib

import pytest

from dsvire.visual_adapters import AdapterError, TextLayoutAdapter, score_document
from dsvire.visual_registry import bind_prediction_scores, load_visual_registry_data


def _pdf() -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Acme A-1 SOIC-8\n"
        "Pin Configuration - top view\n"
        "VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8\n"
        "Pin Functions\n"
        "Pin Name Type Description\n"
        "1 VIN input 2 BOOT passive 3 PH output 4 GND ground\n"
        "5 VSENSE input 6 ENA input 7 COMP passive 8 PWRPAD ground",
    )
    payload = document.tobytes()
    document.close()
    return payload


def _identity(mpn: str = "A-1", package: str = "SOIC-8") -> dict[str, str]:
    return {"manufacturer": "Acme", "mpn": mpn, "package": package}


def _case(
    case_id: str,
    label: str,
    region_type: str,
    *,
    identity: dict[str, str] | None = None,
    view: str = "not_applicable",
) -> dict:
    return {
        "id": case_id,
        "label": label,
        "region_type": region_type,
        "page": 1,
        "bbox_norm": [0.0, 0.0, 1.0, 1.0],
        "view": view,
        "claimed_identity": identity or _identity(),
        "rationale": "Synthetic adapter fixture.",
    }


def _registry(payload: bytes) -> dict:
    return {
        "schema_version": "dsvire.visual-eval-registry.v1",
        "documents": [
            {
                "id": "acme-a1",
                "document_group": "acme-a-family",
                "split": "development",
                "category": "voltage_regulator",
                "source": {"url": "https://example.invalid/a1.pdf", "revision": "test"},
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "redistribution": "redistributable",
                "license_note": "Synthetic fixture.",
                "identity": _identity(),
                "review": {
                    "status": "unreviewed",
                    "reviewers": [],
                    "reviewed_at": None,
                    "annotation_revision": "fixture@1",
                },
                "cases": [
                    _case("pinout", "positive", "pinout", view="top"),
                    _case("table", "positive", "table"),
                    _case("package", "positive", "package"),
                    _case(
                        "wrong-package",
                        "wrong_package",
                        "package",
                        identity=_identity(package="TSSOP-8"),
                    ),
                    _case(
                        "wrong-variant",
                        "wrong_variant",
                        "package",
                        identity=_identity(mpn="A-2"),
                    ),
                    _case("wrong-view", "wrong_view", "pinout", view="bottom"),
                ],
            }
        ],
    }


def test_text_layout_adapter_scores_without_receiving_ground_truth_labels() -> None:
    payload = _pdf()
    registry = load_visual_registry_data(_registry(payload))
    adapter = TextLayoutAdapter()

    scores = score_document(adapter, payload, registry.documents[0])
    predictions = bind_prediction_scores(registry, scores)
    by_id = {prediction.case_id: prediction.score for prediction in predictions}

    assert adapter.metadata.score_semantics == "similarity"
    assert len(adapter.metadata.implementation_sha256) == 64
    assert by_id["acme-a1/pinout"] >= 0.7
    assert by_id["acme-a1/table"] >= 0.72
    assert by_id["acme-a1/package"] == 1.0
    assert by_id["acme-a1/wrong-package"] < 1.0
    assert by_id["acme-a1/wrong-variant"] < 1.0
    assert by_id["acme-a1/wrong-view"] == 0.0


def test_adapter_rejects_source_hash_mismatch() -> None:
    payload = _pdf()
    registry = load_visual_registry_data(_registry(payload))
    with pytest.raises(AdapterError, match="SHA-256 mismatch"):
        score_document(TextLayoutAdapter(), payload + b"changed", registry.documents[0])


def test_adapter_rejects_case_page_outside_document() -> None:
    payload = _pdf()
    data = _registry(payload)
    data["documents"][0]["cases"][0]["page"] = 2
    registry = load_visual_registry_data(data)
    with pytest.raises(AdapterError, match="references page 2"):
        score_document(TextLayoutAdapter(), payload, registry.documents[0])

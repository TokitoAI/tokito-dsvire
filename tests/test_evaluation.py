from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from dsvire.evaluation import RegistryError, evaluate_registry, load_registry_data


def _synthetic_pdf() -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    pinout = document.new_page()
    pinout.insert_text(
        (72, 72),
        "Acme A-1 Active Production SOIC (D) | 8\n"
        "Pin Configuration top view\n"
        "VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
    )
    table = document.new_page()
    table.insert_text(
        (72, 72),
        "Pin Functions\nPin Name Type Description\n"
        "1 VIN input\n2 BOOT passive\n3 PH output\n4 GND ground\n"
        "5 VSENSE input\n6 ENA input\n7 COMP passive\n8 PWRPAD ground",
    )
    payload = document.tobytes()
    document.close()
    return payload


def _registry_data(payload: bytes) -> dict:
    return {
        "schema_version": "dsvire.identity-eval-registry.v1",
        "documents": [
            {
                "id": "acme-a1",
                "document_group": "acme-a-family",
                "split": "development",
                "source": {"url": "https://example.invalid/a1.pdf", "revision": "test"},
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "redistribution": "redistributable",
                "license_note": "Synthetic test document.",
                "identity": {"manufacturer": "Acme", "mpn": "A-1", "package": "SOIC-8"},
                "negatives": [
                    {
                        "id": "near-miss",
                        "identity": {
                            "manufacturer": "Acme",
                            "mpn": "A-10",
                            "package": "SOIC-8",
                        },
                        "expected_error_contains": "exact token-bounded MPN",
                    },
                    {
                        "id": "wrong-package",
                        "identity": {
                            "manufacturer": "Acme",
                            "mpn": "A-1",
                            "package": "TSSOP-8",
                        },
                        "expected_error_contains": "not associated",
                    },
                ],
            }
        ],
    }


def test_evaluation_metrics_are_deterministic_and_fail_closed(tmp_path) -> None:
    payload = _synthetic_pdf()
    registry = load_registry_data(_registry_data(payload))
    first = evaluate_registry(registry, lambda _case: payload, output_root=tmp_path / "first")
    second = evaluate_registry(registry, lambda _case: payload, output_root=tmp_path / "second")

    assert first == second
    assert first["gate_passed"] is True
    assert first["metrics"] == {
        "documents": 1,
        "positives_expected": 1,
        "positives_passed": 1,
        "negatives_expected": 2,
        "negatives_abstained_with_expected_reason": 2,
        "negative_wrong_reason": 0,
        "silent_wrong_identity_acceptances": 0,
    }
    json.dumps(first)


def test_fetched_pdf_hash_mismatch_is_a_hard_error(tmp_path) -> None:
    payload = _synthetic_pdf()
    registry = load_registry_data(_registry_data(payload))
    with pytest.raises(RegistryError, match="source SHA-256 mismatch"):
        evaluate_registry(registry, lambda _case: b"different", output_root=tmp_path)


def test_document_groups_cannot_leak_across_splits() -> None:
    payload = _synthetic_pdf()
    data = _registry_data(payload)
    duplicate = deepcopy(data["documents"][0])
    duplicate["id"] = "acme-a1-evaluation"
    duplicate["split"] = "evaluation"
    data["documents"].append(duplicate)

    with pytest.raises(RegistryError, match="leaks across splits"):
        load_registry_data(data)


def test_wrong_abstention_reason_fails_the_gate(tmp_path) -> None:
    payload = _synthetic_pdf()
    data = _registry_data(payload)
    data["documents"][0]["negatives"][0]["expected_error_contains"] = "different reason"
    registry = load_registry_data(data)
    result = evaluate_registry(registry, lambda _case: payload, output_root=tmp_path)

    assert result["gate_passed"] is False
    assert result["metrics"]["negative_wrong_reason"] == 1


def test_registry_rejects_unknown_fields() -> None:
    payload = _synthetic_pdf()
    data = _registry_data(payload)
    data["documents"][0]["unreviewed"] = True
    with pytest.raises(RegistryError, match="unknown"):
        load_registry_data(data)


def test_committed_registry_is_strict_and_contains_no_pdf_bytes() -> None:
    root = Path(__file__).parents[1]
    registry_path = root / "evaluation/identity_registry.v1.json"
    registry = load_registry_data(json.loads(registry_path.read_text(encoding="utf-8")))

    assert len(registry.documents) == 3
    assert {document.split for document in registry.documents} == {"development"}
    assert all(document.redistribution == "download_only" for document in registry.documents)
    assert not list((root / "evaluation").glob("*.pdf"))

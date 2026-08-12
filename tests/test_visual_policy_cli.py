from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsvire.visual_metrics import freeze_policy
from dsvire.visual_policy_artifact import adapter_identity, policy, predictions


def _artifact(split: str = "calibration") -> dict:
    return {
        "schema_version": "dsvire.visual-adapter-benchmark.v1",
        "dataset_sha256": "d" * 64,
        "selected_split": split,
        "score_sha256": "s" * 64,
        "adapter": {
            "adapter_id": "fixture@1",
            "implementation_sha256": "a" * 64,
            "model_sha256": None,
            "preprocessing_id": "fixture-preprocess@1",
            "score_semantics": "similarity",
        },
        "documents": [
            {
                "id": "acme-a1",
                "document_group": "acme-a-family",
                "split": split,
                "scores": [
                    {"case_id": "acme-a1/positive", "label": "positive", "score": 0.9},
                    {
                        "case_id": "acme-a1/wrong-variant",
                        "label": "wrong_variant",
                        "score": 0.4,
                    },
                ],
            }
        ],
    }


def test_split_artifact_builds_predictions_and_uses_implementation_as_model_digest() -> None:
    artifact = _artifact()
    values = predictions(artifact, "calibration")
    assert {prediction.split for prediction in values} == {"calibration"}
    assert adapter_identity(artifact) == (
        "fixture@1",
        "a" * 64,
        "fixture-preprocess@1",
        "similarity",
    )


def test_policy_artifact_digest_is_revalidated() -> None:
    artifact = _artifact()
    identity = adapter_identity(artifact)
    frozen_policy, _metrics = freeze_policy(
        predictions(artifact, "calibration"),
        model_id=identity[0],
        model_sha256=identity[1],
        preprocessing_id=identity[2],
        dataset_sha256=artifact["dataset_sha256"],
        score_semantics=identity[3],
    )
    value = {"policy": frozen_policy.as_dict(), "policy_sha256": frozen_policy.policy_sha256}
    assert policy(value) == frozen_policy
    value["policy_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        policy(value)


def test_evaluation_artifact_cannot_be_consumed_as_calibration() -> None:
    with pytest.raises(ValueError, match="--split calibration"):
        predictions(_artifact("evaluation"), "calibration")


def test_committed_registry_materializes_only_reviewed_pre_registered_calibration() -> None:
    root = Path(__file__).parents[1]
    registry = json.loads((root / "evaluation/visual_registry.v1.json").read_text())
    plan = json.loads((root / "evaluation/visual_split_plan.v1.json").read_text())
    planned = {family["id"]: family for family in plan["families"]}
    calibration = [
        document for document in registry["documents"] if document["split"] == "calibration"
    ]
    assert len(calibration) == 5
    assert not any(document["split"] == "evaluation" for document in registry["documents"])
    for document in calibration:
        assert planned[document["id"]]["split"] == "calibration"
        assert planned[document["id"]]["content_sha256"] == document["content_sha256"]
        assert document["review"]["status"] == "reviewed"

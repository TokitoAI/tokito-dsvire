"""Strict parsing boundary between split benchmark, policy, and held-out artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .visual_metrics import FrozenPolicy, Prediction


def load_artifact(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def predictions(artifact: dict[str, Any], expected_split: str) -> list[Prediction]:
    if artifact.get("schema_version") != "dsvire.visual-adapter-benchmark.v1":
        raise ValueError("unsupported benchmark artifact schema")
    if artifact.get("selected_split") != expected_split:
        raise ValueError(f"artifact must be generated with --split {expected_split}")
    documents = artifact.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("benchmark artifact has no documents")
    values: list[Prediction] = []
    for index, document in enumerate(documents):
        if not isinstance(document, dict) or document.get("split") != expected_split:
            raise ValueError(f"documents[{index}] is not isolated to {expected_split}")
        scores = document.get("scores")
        if not isinstance(scores, list) or not scores:
            raise ValueError(f"documents[{index}] has no scores")
        for score in scores:
            if not isinstance(score, dict):
                raise ValueError(f"documents[{index}] contains an invalid score")
            values.append(
                Prediction.parse(
                    {
                        "case_id": score["case_id"],
                        "document_group": document["document_group"],
                        "split": expected_split,
                        "label": score["label"],
                        "score": score["score"],
                    }
                )
            )
    return values


def adapter_identity(artifact: dict[str, Any]) -> tuple[str, str, str, str]:
    adapter = artifact.get("adapter")
    if not isinstance(adapter, dict):
        raise ValueError("benchmark artifact has no adapter metadata")
    model_sha256 = adapter.get("model_sha256") or adapter.get("implementation_sha256")
    values = (
        adapter.get("adapter_id"),
        model_sha256,
        adapter.get("preprocessing_id"),
        adapter.get("score_semantics"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError("benchmark adapter identity is incomplete")
    return cast(tuple[str, str, str, str], values)


def policy(value: dict[str, Any]) -> FrozenPolicy:
    data = value.get("policy")
    if not isinstance(data, dict):
        raise ValueError("policy artifact has no policy")
    expected = FrozenPolicy(
        model_id=data["model_id"],
        model_sha256=data["model_sha256"],
        preprocessing_id=data["preprocessing_id"],
        dataset_sha256=data["dataset_sha256"],
        score_semantics=data["score_semantics"],
        calibration_id=data["calibration_id"],
        threshold=data["threshold"],
        maximum_wrong_visual_rate=data["maximum_wrong_visual_rate"],
        minimum_positive_coverage=data["minimum_positive_coverage"],
        require_zero_wrong_identity=data["require_zero_wrong_identity"],
    )
    if value.get("policy_sha256") != expected.policy_sha256:
        raise ValueError("policy artifact digest mismatch")
    return expected

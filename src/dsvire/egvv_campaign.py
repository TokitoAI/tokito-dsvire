"""EGVV train/calibrate/freeze/evaluate-once campaign. No silent heuristic fallback."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .cycle_execution import CycleStatus, assert_score_access_authorized
from .visual_metrics import (
    FrozenPolicy,
    Prediction,
    VisualMetricError,
    evaluate_policy,
    freeze_policy,
)

Outcome = Literal["accepted", "rejected", "abstained"]


class EgvvCampaignError(ValueError):
    """EGVV calibration or evaluation violated the freeze-then-eval-once contract."""


@dataclass(frozen=True)
class EgvvDecision:
    outcome: Outcome
    score: float
    score_semantics: str


def decide(score: float, policy: FrozenPolicy) -> EgvvDecision:
    if policy.score_semantics != "calibrated_probability":
        raise EgvvCampaignError(
            "EGVV production decisions require calibrated_probability semantics"
        )
    if not 0 <= score <= 1:
        raise EgvvCampaignError("EGVV score must be within 0..=1")
    if score > policy.threshold:
        outcome: Outcome = "accepted"
    elif score == 0:
        outcome = "rejected"
    else:
        outcome = "abstained"
    return EgvvDecision(outcome, score, policy.score_semantics)


def calibrate(
    predictions: Sequence[Prediction],
    *,
    status: CycleStatus,
    model_id: str,
    model_sha256: str,
    preprocessing_id: str,
    dataset_sha256: str,
    calibration_id: str,
) -> FrozenPolicy:
    assert_score_access_authorized(status)
    if any(item.split == "evaluation" for item in predictions):
        raise EgvvCampaignError("calibration must not observe evaluation predictions")
    try:
        policy, counts = freeze_policy(
            predictions,
            model_id=model_id,
            model_sha256=model_sha256,
            preprocessing_id=preprocessing_id,
            dataset_sha256=dataset_sha256,
            score_semantics="calibrated_probability",
            calibration_id=calibration_id,
            maximum_wrong_visual_rate=0.02,
            minimum_positive_coverage=0.5,
        )
    except VisualMetricError as exc:
        raise EgvvCampaignError(str(exc)) from exc
    if counts["wrong_identity_accepted"] != 0:
        raise EgvvCampaignError("calibration accepted a wrong-variant or wrong-package case")
    return policy


def evaluate_once(
    predictions: Sequence[Prediction],
    policy: FrozenPolicy,
    *,
    status: CycleStatus,
    expected_policy_sha256: str,
) -> dict[str, float | int | bool | str]:
    assert_score_access_authorized(status)
    if policy.policy_sha256 != expected_policy_sha256:
        raise EgvvCampaignError("held-out evaluation policy digest does not match the freeze")
    if any(item.split != "evaluation" for item in predictions):
        raise EgvvCampaignError(
            "held-out evaluation must contain only evaluation split predictions"
        )
    try:
        result = evaluate_policy(predictions, policy)
    except VisualMetricError as exc:
        raise EgvvCampaignError(str(exc)) from exc
    metrics = result["metrics"]
    return {
        "schema_version": result["schema_version"],
        "policy_sha256": result["policy_sha256"],
        "gate_passed": bool(result["gate_passed"]),
        "wrong_visual_rate": float(metrics["wrong_visual_rate"]),
        "wrong_identity_accepted": int(metrics["wrong_identity_accepted"]),
        "positive_coverage": float(metrics["positive_coverage"]),
        "passed_wrong_figure_gate": bool(result["gate_passed"]),
    }

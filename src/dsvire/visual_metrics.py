"""Deterministic calibration and held-out metrics for visual verification.

This module does not run a model. It is the policy boundary shared by every
candidate adapter: adapters emit one bounded score per reviewed case, then this
code freezes a threshold on the calibration split and evaluates it unchanged on
the held-out split. Raw similarity and model self-confidence never become an
EGVV probability merely by passing through this module.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

RESULT_VERSION = "dsvire.visual-verifier-eval.v1"
POLICY_VERSION = "dsvire.egvv-policy.v1"
METRIC_VERSION = "dsvire.selective-metrics@1.0.0"
ALLOWED_SPLITS = {"development", "calibration", "evaluation"}
POSITIVE = "positive"
WRONG_VISUAL = {"wrong_figure", "wrong_view"}
WRONG_IDENTITY = {"wrong_package", "wrong_variant"}
ALLOWED_LABELS = {POSITIVE, *WRONG_VISUAL, *WRONG_IDENTITY}
ALLOWED_SCORE_SEMANTICS = {"similarity", "calibrated_probability"}
SHA256 = re.compile(r"[0-9a-f]{64}")


class VisualMetricError(ValueError):
    """Prediction or policy data violates the calibration contract."""


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualMetricError(f"{context} must be non-empty text")
    return value.strip()


@dataclasses.dataclass(frozen=True)
class Prediction:
    case_id: str
    document_group: str
    split: str
    label: str
    score: float

    @classmethod
    def parse(cls, value: Any, context: str = "prediction") -> Prediction:
        if not isinstance(value, Mapping):
            raise VisualMetricError(f"{context} must be an object")
        required = {"case_id", "document_group", "split", "label", "score"}
        if set(value) != required:
            raise VisualMetricError(
                f"{context} keys invalid: missing={sorted(required - set(value))}, "
                f"unknown={sorted(set(value) - required)}"
            )
        split = _text(value["split"], f"{context}.split")
        if split not in ALLOWED_SPLITS:
            raise VisualMetricError(f"{context}.split is unsupported: {split!r}")
        label = _text(value["label"], f"{context}.label")
        if label not in ALLOWED_LABELS:
            raise VisualMetricError(f"{context}.label is unsupported: {label!r}")
        score = value["score"]
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise VisualMetricError(f"{context}.score must be finite within 0..=1")
        return cls(
            _text(value["case_id"], f"{context}.case_id"),
            _text(value["document_group"], f"{context}.document_group"),
            split,
            label,
            float(score),
        )


@dataclasses.dataclass(frozen=True)
class FrozenPolicy:
    model_id: str
    model_sha256: str
    preprocessing_id: str
    dataset_sha256: str
    score_semantics: str
    calibration_id: str | None
    threshold: float
    maximum_wrong_visual_rate: float
    minimum_positive_coverage: float
    require_zero_wrong_identity: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_VERSION,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "preprocessing_id": self.preprocessing_id,
            "dataset_sha256": self.dataset_sha256,
            "metric_version": METRIC_VERSION,
            "score_semantics": self.score_semantics,
            "calibration_id": self.calibration_id,
            "accept_when": "score_gt_threshold",
            "threshold": self.threshold,
            "maximum_wrong_visual_rate": self.maximum_wrong_visual_rate,
            "minimum_positive_coverage": self.minimum_positive_coverage,
            "require_zero_wrong_identity": self.require_zero_wrong_identity,
        }

    @property
    def policy_sha256(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _validated_predictions(values: Iterable[Prediction]) -> tuple[Prediction, ...]:
    predictions = tuple(values)
    if not predictions:
        raise VisualMetricError("predictions must not be empty")
    ids: set[str] = set()
    group_splits: dict[str, str] = {}
    for prediction in predictions:
        if prediction.case_id in ids:
            raise VisualMetricError(f"duplicate prediction case_id: {prediction.case_id}")
        ids.add(prediction.case_id)
        previous = group_splits.setdefault(prediction.document_group, prediction.split)
        if previous != prediction.split:
            raise VisualMetricError(
                f"document group {prediction.document_group!r} leaks across splits"
            )
    return predictions


def _accepted(prediction: Prediction, threshold: float) -> bool:
    # Strict greater-than makes threshold=1.0 a defined fail-closed policy that
    # accepts nothing, even if an adapter emits a saturated score.
    return prediction.score > threshold


def _selective_counts(
    predictions: Iterable[Prediction], threshold: float
) -> dict[str, int | float]:
    values = tuple(predictions)
    accepted = tuple(value for value in values if _accepted(value, threshold))
    positives = sum(value.label == POSITIVE for value in values)
    accepted_positive = sum(value.label == POSITIVE for value in accepted)
    wrong_visual = sum(value.label in WRONG_VISUAL for value in accepted)
    wrong_identity = sum(value.label in WRONG_IDENTITY for value in accepted)
    return {
        "cases": len(values),
        "accepted": len(accepted),
        "positives": positives,
        "accepted_positives": accepted_positive,
        "positive_coverage": accepted_positive / positives if positives else 0.0,
        "wrong_visual_accepted": wrong_visual,
        "wrong_identity_accepted": wrong_identity,
        "wrong_visual_rate": wrong_visual / len(accepted) if accepted else 0.0,
    }


def freeze_policy(
    predictions: Iterable[Prediction],
    *,
    model_id: str,
    model_sha256: str,
    preprocessing_id: str,
    dataset_sha256: str,
    score_semantics: str,
    calibration_id: str | None = None,
    maximum_wrong_visual_rate: float = 0.02,
    minimum_positive_coverage: float = 0.5,
) -> tuple[FrozenPolicy, dict[str, int | float]]:
    values = _validated_predictions(predictions)
    calibration = tuple(value for value in values if value.split == "calibration")
    if not calibration:
        raise VisualMetricError("calibration split is empty")
    if not any(value.label == POSITIVE for value in calibration):
        raise VisualMetricError("calibration split has no positive cases")
    for name, digest in (("model_sha256", model_sha256), ("dataset_sha256", dataset_sha256)):
        if SHA256.fullmatch(digest) is None:
            raise VisualMetricError(f"{name} must be lowercase SHA-256")
    if not 0 <= maximum_wrong_visual_rate <= 1:
        raise VisualMetricError("maximum_wrong_visual_rate must be within 0..=1")
    if not 0 <= minimum_positive_coverage <= 1:
        raise VisualMetricError("minimum_positive_coverage must be within 0..=1")
    if score_semantics not in ALLOWED_SCORE_SEMANTICS:
        raise VisualMetricError(f"score_semantics must be one of {sorted(ALLOWED_SCORE_SEMANTICS)}")

    # Every observed score is a deterministic decision boundary. Threshold 1.0
    # is always included as the safe abstain-all fallback.
    candidates = sorted({1.0, *(value.score for value in calibration)})
    feasible: list[tuple[float, dict[str, int | float]]] = []
    for threshold in candidates:
        counts = _selective_counts(calibration, threshold)
        if (
            counts["wrong_identity_accepted"] == 0
            and counts["wrong_visual_rate"] <= maximum_wrong_visual_rate
        ):
            feasible.append((threshold, counts))
    # Maximize accepted positives, then prefer the stricter threshold. This
    # makes the result independent of input ordering and conservative on ties.
    threshold, counts = max(
        feasible,
        key=lambda item: (item[1]["accepted_positives"], item[0]),
    )
    if score_semantics == "calibrated_probability":
        calibration_id = _text(calibration_id, "calibration_id")
    elif calibration_id is not None:
        raise VisualMetricError("similarity scores cannot name a probability calibration")
    policy = FrozenPolicy(
        model_id=_text(model_id, "model_id"),
        model_sha256=model_sha256,
        preprocessing_id=_text(preprocessing_id, "preprocessing_id"),
        dataset_sha256=dataset_sha256,
        score_semantics=score_semantics,
        calibration_id=calibration_id,
        threshold=threshold,
        maximum_wrong_visual_rate=maximum_wrong_visual_rate,
        minimum_positive_coverage=minimum_positive_coverage,
    )
    return policy, counts


def _score_metrics(predictions: tuple[Prediction, ...], score_semantics: str) -> dict[str, float]:
    targets = [1.0 if value.label == POSITIVE else 0.0 for value in predictions]
    ordered = sorted(predictions, key=lambda value: (-value.score, value.case_id))
    wrong = 0
    risk_sum = 0.0
    for rank, value in enumerate(ordered, 1):
        wrong += value.label != POSITIVE
        risk_sum += wrong / rank
    metrics = {"aurc": risk_sum / len(ordered)}
    if score_semantics == "calibrated_probability":
        brier = sum(
            (value.score - target) ** 2 for value, target in zip(predictions, targets, strict=True)
        ) / len(predictions)
        ece = 0.0
        for index in range(10):
            lower = index / 10
            upper = (index + 1) / 10
            bucket = [
                (value, target)
                for value, target in zip(predictions, targets, strict=True)
                if lower <= value.score < upper or (index == 9 and value.score == 1.0)
            ]
            if not bucket:
                continue
            confidence = sum(value.score for value, _target in bucket) / len(bucket)
            accuracy = sum(target for _value, target in bucket) / len(bucket)
            ece += len(bucket) / len(predictions) * abs(accuracy - confidence)
        metrics.update({"brier": brier, "ece_10_bin": ece})
    return metrics


def evaluate_policy(predictions: Iterable[Prediction], policy: FrozenPolicy) -> dict[str, Any]:
    values = _validated_predictions(predictions)
    evaluation = tuple(value for value in values if value.split == "evaluation")
    if not evaluation:
        raise VisualMetricError("evaluation split is empty")
    counts = _selective_counts(evaluation, policy.threshold)
    score_metrics = _score_metrics(evaluation, policy.score_semantics)
    gate_passed = (
        counts["wrong_identity_accepted"] == 0
        and counts["wrong_visual_rate"] <= policy.maximum_wrong_visual_rate
        and counts["positive_coverage"] >= policy.minimum_positive_coverage
    )
    return {
        "schema_version": RESULT_VERSION,
        "metric_version": METRIC_VERSION,
        "policy": policy.as_dict(),
        "policy_sha256": policy.policy_sha256,
        "gate_passed": gate_passed,
        "metrics": {**counts, **score_metrics},
    }

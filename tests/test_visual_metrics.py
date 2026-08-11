from __future__ import annotations

from copy import deepcopy

import pytest

from dsvire.visual_metrics import (
    Prediction,
    VisualMetricError,
    evaluate_policy,
    freeze_policy,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _prediction(case_id: str, split: str, label: str, score: float) -> Prediction:
    return Prediction.parse(
        {
            "case_id": case_id,
            "document_group": f"group-{case_id}",
            "split": split,
            "label": label,
            "score": score,
        }
    )


def _calibration() -> list[Prediction]:
    return [
        _prediction("cal-pos-high", "calibration", "positive", 0.95),
        _prediction("cal-pos-mid", "calibration", "positive", 0.80),
        _prediction("cal-wrong-figure", "calibration", "wrong_figure", 0.79),
        _prediction("cal-wrong-variant", "calibration", "wrong_variant", 0.60),
    ]


def test_freeze_policy_chooses_maximum_safe_coverage_deterministically() -> None:
    policy, metrics = freeze_policy(
        reversed(_calibration()),
        model_id="candidate@1",
        model_sha256=DIGEST_A,
        preprocessing_id="crop-rgb@1",
        dataset_sha256=DIGEST_B,
        score_semantics="calibrated_probability",
        calibration_id="isotonic@1",
    )

    assert policy.threshold == 0.79
    assert metrics["accepted_positives"] == 2
    assert metrics["wrong_visual_accepted"] == 0
    assert metrics["wrong_identity_accepted"] == 0
    assert len(policy.policy_sha256) == 64


def test_saturated_unsafe_scores_fall_back_to_abstain_all() -> None:
    values = [
        _prediction("positive", "calibration", "positive", 1.0),
        _prediction("wrong", "calibration", "wrong_variant", 1.0),
    ]
    policy, metrics = freeze_policy(
        values,
        model_id="unsafe@1",
        model_sha256=DIGEST_A,
        preprocessing_id="crop@1",
        dataset_sha256=DIGEST_B,
        score_semantics="calibrated_probability",
        calibration_id="isotonic@1",
    )

    assert policy.threshold == 1.0
    assert metrics["accepted"] == 0


def test_held_out_policy_reports_calibration_and_selective_risk_metrics() -> None:
    policy, _metrics = freeze_policy(
        _calibration(),
        model_id="candidate@1",
        model_sha256=DIGEST_A,
        preprocessing_id="crop-rgb@1",
        dataset_sha256=DIGEST_B,
        score_semantics="calibrated_probability",
        calibration_id="isotonic@1",
    )
    evaluation = [
        _prediction("eval-pos", "evaluation", "positive", 0.9),
        _prediction("eval-abstain-pos", "evaluation", "positive", 0.5),
        _prediction("eval-wrong-figure", "evaluation", "wrong_figure", 0.4),
        _prediction("eval-wrong-variant", "evaluation", "wrong_variant", 0.2),
    ]

    result = evaluate_policy(evaluation, policy)

    assert result["gate_passed"] is True
    assert result["metrics"]["positive_coverage"] == 0.5
    assert result["metrics"]["wrong_visual_accepted"] == 0
    assert 0 <= result["metrics"]["brier"] <= 1
    assert 0 <= result["metrics"]["ece_10_bin"] <= 1
    assert 0 <= result["metrics"]["aurc"] <= 1


def test_held_out_wrong_variant_acceptance_fails_gate() -> None:
    policy, _metrics = freeze_policy(
        _calibration(),
        model_id="candidate@1",
        model_sha256=DIGEST_A,
        preprocessing_id="crop-rgb@1",
        dataset_sha256=DIGEST_B,
        score_semantics="calibrated_probability",
        calibration_id="isotonic@1",
    )
    result = evaluate_policy(
        [
            _prediction("eval-pos", "evaluation", "positive", 0.9),
            _prediction("eval-wrong", "evaluation", "wrong_variant", 0.9),
        ],
        policy,
    )
    assert result["gate_passed"] is False
    assert result["metrics"]["wrong_identity_accepted"] == 1


def test_split_leakage_duplicate_ids_and_nonfinite_scores_fail_closed() -> None:
    parsed = Prediction.parse(
        {
            "case_id": "same",
            "document_group": "family",
            "split": "calibration",
            "label": "positive",
            "score": 0.9,
        }
    )
    leaked = deepcopy(parsed)
    object.__setattr__(leaked, "case_id", "other")
    object.__setattr__(leaked, "split", "evaluation")
    with pytest.raises(VisualMetricError, match="leaks across splits"):
        freeze_policy(
            [parsed, leaked],
            model_id="candidate@1",
            model_sha256=DIGEST_A,
            preprocessing_id="crop@1",
            dataset_sha256=DIGEST_B,
            score_semantics="calibrated_probability",
            calibration_id="isotonic@1",
        )

    with pytest.raises(VisualMetricError, match="finite"):
        Prediction.parse(
            {
                "case_id": "bad",
                "document_group": "bad",
                "split": "calibration",
                "label": "positive",
                "score": float("nan"),
            }
        )


def test_calibration_cannot_use_development_or_evaluation_cases() -> None:
    with pytest.raises(VisualMetricError, match="calibration split is empty"):
        freeze_policy(
            [_prediction("dev", "development", "positive", 0.9)],
            model_id="candidate@1",
            model_sha256=DIGEST_A,
            preprocessing_id="crop@1",
            dataset_sha256=DIGEST_B,
            score_semantics="calibrated_probability",
            calibration_id="isotonic@1",
        )


def test_similarity_scores_do_not_claim_probability_metrics() -> None:
    policy, _metrics = freeze_policy(
        _calibration(),
        model_id="encoder@1",
        model_sha256=DIGEST_A,
        preprocessing_id="crop@1",
        dataset_sha256=DIGEST_B,
        score_semantics="similarity",
    )
    result = evaluate_policy(
        [
            _prediction("eval-pos", "evaluation", "positive", 0.9),
            _prediction("eval-neg", "evaluation", "wrong_figure", 0.2),
        ],
        policy,
    )
    assert "aurc" in result["metrics"]
    assert "brier" not in result["metrics"]
    assert "ece_10_bin" not in result["metrics"]


def test_probability_semantics_require_a_named_calibration() -> None:
    with pytest.raises(VisualMetricError, match="calibration_id"):
        freeze_policy(
            _calibration(),
            model_id="candidate@1",
            model_sha256=DIGEST_A,
            preprocessing_id="crop@1",
            dataset_sha256=DIGEST_B,
            score_semantics="calibrated_probability",
        )


def test_abstain_all_policy_does_not_pass_the_coverage_gate() -> None:
    policy, _metrics = freeze_policy(
        [
            _prediction("cal-pos", "calibration", "positive", 1.0),
            _prediction("cal-wrong", "calibration", "wrong_variant", 1.0),
        ],
        model_id="unsafe@1",
        model_sha256=DIGEST_A,
        preprocessing_id="crop@1",
        dataset_sha256=DIGEST_B,
        score_semantics="calibrated_probability",
        calibration_id="isotonic@1",
    )
    result = evaluate_policy(
        [
            _prediction("eval-pos", "evaluation", "positive", 1.0),
            _prediction("eval-wrong", "evaluation", "wrong_variant", 1.0),
        ],
        policy,
    )
    assert result["metrics"]["accepted"] == 0
    assert result["gate_passed"] is False

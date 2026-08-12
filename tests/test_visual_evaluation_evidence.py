from __future__ import annotations

import json
from pathlib import Path

from dsvire.visual_policy_artifact import load_artifact, policy, predictions


def test_committed_evaluation_is_bound_to_frozen_policy_and_fails_closed() -> None:
    root = Path(__file__).parents[1]
    benchmark = load_artifact(
        root / "evaluation/results/visual-evaluation-text-layout-2026-08-12.json"
    )
    frozen = load_artifact(
        root / "evaluation/results/visual-policy-text-layout-calibration-2026-08-12.json"
    )
    result = json.loads(
        (root / "evaluation/results/visual-evaluation-policy-result-2026-08-12.json").read_text()
    )
    assert len(predictions(benchmark, "evaluation")) == 35
    assert benchmark["dataset_sha256"] == policy(frozen).dataset_sha256
    assert result["policy_sha256"] == frozen["policy_sha256"]
    assert result["evaluation_score_sha256"] == benchmark["score_sha256"]
    assert result["gate_passed"] is False
    assert result["metrics"]["positive_coverage"] == 7 / 15
    assert result["metrics"]["wrong_visual_accepted"] == 0
    assert result["metrics"]["wrong_identity_accepted"] == 0

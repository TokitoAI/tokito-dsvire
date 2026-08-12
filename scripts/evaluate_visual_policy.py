"""Freeze a calibration policy, then evaluate a separately produced held-out artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.visual_metrics import evaluate_policy, freeze_policy
from dsvire.visual_policy_artifact import (
    adapter_identity,
    load_artifact,
    predictions,
)
from dsvire.visual_policy_artifact import (
    policy as load_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--calibration-benchmark", type=Path, required=True)
    freeze.add_argument("--json-out", type=Path, required=True)
    freeze.add_argument("--minimum-positive-coverage", type=float, default=0.5)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--evaluation-benchmark", type=Path, required=True)
    evaluate.add_argument("--policy", type=Path, required=True)
    evaluate.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "freeze":
            artifact = load_artifact(args.calibration_benchmark)
            model_id, model_sha256, preprocessing_id, semantics = adapter_identity(artifact)
            dataset_sha256 = artifact.get("dataset_sha256")
            if not isinstance(dataset_sha256, str):
                raise ValueError("benchmark does not bind the full dataset digest")
            frozen_policy, metrics = freeze_policy(
                predictions(artifact, "calibration"),
                model_id=model_id,
                model_sha256=model_sha256,
                preprocessing_id=preprocessing_id,
                dataset_sha256=dataset_sha256,
                score_semantics=semantics,
                minimum_positive_coverage=args.minimum_positive_coverage,
            )
            result = {
                "schema_version": "dsvire.visual-policy-freeze.v1",
                "calibration_score_sha256": artifact["score_sha256"],
                "policy": frozen_policy.as_dict(),
                "policy_sha256": frozen_policy.policy_sha256,
                "calibration_metrics": metrics,
            }
        else:
            artifact = load_artifact(args.evaluation_benchmark)
            frozen_policy = load_policy(load_artifact(args.policy))
            model_id, model_sha256, preprocessing_id, semantics = adapter_identity(artifact)
            if (model_id, model_sha256, preprocessing_id, semantics) != (
                frozen_policy.model_id,
                frozen_policy.model_sha256,
                frozen_policy.preprocessing_id,
                frozen_policy.score_semantics,
            ):
                raise ValueError("evaluation adapter identity does not match frozen policy")
            if artifact.get("dataset_sha256") != frozen_policy.dataset_sha256:
                raise ValueError("evaluation dataset does not match frozen policy")
            result = evaluate_policy(predictions(artifact, "evaluation"), frozen_policy)
            result["evaluation_score_sha256"] = artifact["score_sha256"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    args.json_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

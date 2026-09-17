"""Export sealed cycle v5 authoring into visual/query registries for scoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.cycle_eval_export import export_sealed_cycle_eval_artifacts

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path, default=ROOT / "evaluation/retrieval_cycle_v5_preregistration.json"
    )
    parser.add_argument(
        "--packet", type=Path, default=ROOT / "evaluation/retrieval_cycle_v5_authoring_packet.json"
    )
    parser.add_argument(
        "--submission",
        type=Path,
        default=ROOT / "evaluation/retrieval_cycle_v5_authoring_submission.json",
    )
    parser.add_argument(
        "--seal", type=Path, default=ROOT / "evaluation/retrieval_cycle_v5_authoring_seal.json"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "evaluation/retrieval_cycle_v5_source_manifest.json",
    )
    parser.add_argument(
        "--visual-out",
        type=Path,
        default=ROOT / "evaluation/retrieval_cycle_v5_visual_registry.json",
    )
    parser.add_argument(
        "--queries-out",
        type=Path,
        default=ROOT / "evaluation/retrieval_cycle_v5_query_registry.json",
    )
    parser.add_argument(
        "--split-plan-out",
        type=Path,
        default=ROOT / "evaluation/retrieval_cycle_v5_visual_split_plan.json",
    )
    args = parser.parse_args()
    artifacts = export_sealed_cycle_eval_artifacts(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.packet.read_text(encoding="utf-8")),
        json.loads(args.submission.read_text(encoding="utf-8")),
        json.loads(args.seal.read_text(encoding="utf-8")),
        json.loads(args.manifest.read_text(encoding="utf-8")),
    )
    outputs = {
        args.visual_out: artifacts["visual_registry"],
        args.queries_out: artifacts["query_registry"],
        args.split_plan_out: artifacts["split_plan"],
    }
    for path, value in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    print(
        json.dumps(
            {
                "plan_id": artifacts["plan_id"],
                "seal_sha256": artifacts["seal_sha256"],
                "submission_sha256": artifacts["submission_sha256"],
                "visual_registry_sha256": artifacts["visual_registry_sha256"],
                "documents": len(artifacts["visual_registry"]["documents"]),
                "queries": len(artifacts["query_registry"]["queries"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a deterministic contract canary over each query's closed judged pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dsvire.corpus_coverage import load_query_registry
from dsvire.query_ranking import load_ranking_artifact
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ID = "dsvire-judgment-order-canary@1"
SYSTEM_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build(visual_path: Path, query_path: Path) -> dict[str, object]:
    visual = load_visual_registry_data(json.loads(visual_path.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(query_path.read_text(encoding="utf-8")), visual)
    rankings = []
    for query in queries.queries:
        candidates = [case_id for case_id, _grade in query.relevance_judgments] + list(
            query.hard_negative_case_ids
        )
        rankings.append(
            {
                "query_id": query.query_id,
                "candidates": [
                    {"case_id": case_id, "score": float(len(candidates) - index)}
                    for index, case_id in enumerate(candidates)
                ],
            }
        )
    result: dict[str, object] = {
        "schema_version": "dsvire.query-ranking.v1",
        "query_registry_sha256": queries.content_sha256,
        "visual_registry_sha256": visual.content_sha256,
        "system": {"id": SYSTEM_ID, "sha256": SYSTEM_SHA256},
        "rankings": rankings,
    }
    load_ranking_artifact(result, queries, visual)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "evaluation/results/query-ranking-canary.v1.json"
    )
    args = parser.parse_args()
    result = build(args.registry, args.queries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

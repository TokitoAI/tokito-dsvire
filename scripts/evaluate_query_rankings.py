"""Validate and evaluate a source-free DS-ViRe query ranking artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.corpus_coverage import load_query_registry
from dsvire.query_ranking import evaluate_rankings, load_ranking_artifact
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ranking", type=Path)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument("--json-out", required=True, type=Path)
    args = parser.parse_args()
    visual = load_visual_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(args.queries.read_text(encoding="utf-8")), visual)
    artifact = load_ranking_artifact(
        json.loads(args.ranking.read_text(encoding="utf-8")), queries, visual
    )
    result = evaluate_rankings(queries, artifact)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

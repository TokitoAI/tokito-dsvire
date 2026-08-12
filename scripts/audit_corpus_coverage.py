"""Emit the deterministic Technical Bible corpus coverage ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.corpus_coverage import (
    audit_corpus_coverage,
    load_coverage_policy,
    load_query_registry,
)
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "evaluation/corpus_coverage_policy.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    registry = load_visual_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
    policy = load_coverage_policy(json.loads(args.policy.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(args.queries.read_text(encoding="utf-8")), registry)
    result = audit_corpus_coverage(registry, policy, queries)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the deterministic development-only query tranche from positive cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.corpus_coverage import load_query_registry
from dsvire.visual_registry import VisualCase, VisualDocument, load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = "scripts/build_development_queries.py@2"
INTENTS = ("pinout", "table", "package")


def _query_text(document: VisualDocument, intent: str) -> str:
    mpn = document.identity.mpn
    package = document.identity.package
    if intent == "pinout":
        return f"Show the {mpn} {package} pinout."
    if intent == "table":
        return f"Find the {mpn} pin-function table."
    if intent == "package":
        return f"Find the {mpn} {package} package drawing."
    raise ValueError(f"unsupported query intent: {intent}")


def _positive(document: VisualDocument, intent: str) -> VisualCase:
    matches = [
        case for case in document.cases if case.label == "positive" and case.region_type == intent
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{document.document_id}: expected exactly one positive {intent} case, got {len(matches)}"
        )
    return matches[0]


def build(registry_data: dict[str, object]) -> dict[str, object]:
    registry = load_visual_registry_data(registry_data)
    queries: list[dict[str, object]] = []
    for document in sorted(registry.documents, key=lambda item: item.document_id):
        if document.split != "development":
            continue
        for intent in INTENTS:
            case = _positive(document, intent)
            queries.append(
                {
                    "id": f"{document.document_id}/{intent}-query-1",
                    "document_group": document.document_group,
                    "split": "development",
                    "query_text": _query_text(document, intent),
                    "query_type": intent,
                    "relevance_judgments": [
                        {"case_id": f"{document.document_id}/{case.case_id}", "grade": 2}
                    ],
                    "hard_negative_case_ids": [
                        f"{document.document_id}/{candidate.case_id}"
                        for candidate in sorted(document.cases, key=lambda item: item.case_id)
                        if candidate.case_id != case.case_id
                    ],
                    "provenance": {
                        "method": "deterministic_template",
                        "generator": GENERATOR,
                        "independently_reviewed": False,
                    },
                }
            )
    result: dict[str, object] = {
        "schema_version": "dsvire.query-registry.v2",
        "queries": queries,
    }
    validated = load_query_registry(result, registry)
    expected = 3 * sum(document.split == "development" for document in registry.documents)
    if len(validated.queries) != expected:
        raise ValueError(f"expected {expected} development queries, got {len(validated.queries)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    args = parser.parse_args()
    registry_data = json.loads(args.registry.read_text(encoding="utf-8"))
    result = build(registry_data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

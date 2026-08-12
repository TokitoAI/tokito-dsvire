from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from dsvire.corpus_coverage import load_query_registry
from dsvire.query_ranking import QueryRankingError, evaluate_rankings, load_ranking_artifact
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).parents[1]


def _inputs():
    visual = load_visual_registry_data(
        json.loads((ROOT / "evaluation/visual_registry.v1.json").read_text())
    )
    queries = load_query_registry(
        json.loads((ROOT / "evaluation/query_registry.v2.json").read_text()), visual
    )
    ranking = json.loads((ROOT / "evaluation/results/query-ranking-canary.v1.json").read_text())
    return visual, queries, ranking


def test_committed_canary_is_complete_and_byte_stable(tmp_path: Path) -> None:
    output = tmp_path / "ranking.json"
    subprocess.run(
        [sys.executable, "scripts/build_query_ranking_baseline.py", "--out", str(output)],
        cwd=ROOT,
        check=True,
    )
    assert (
        output.read_bytes()
        == (ROOT / "evaluation/results/query-ranking-canary.v1.json").read_bytes()
    )


def test_committed_query_and_ranking_contracts_are_schema_valid() -> None:
    query_schema = json.loads((ROOT / "scripts/schema/query_registry_v2.schema.json").read_text())
    ranking_schema = json.loads((ROOT / "scripts/schema/query_ranking_v1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(query_schema)
    jsonschema.Draft202012Validator.check_schema(ranking_schema)
    jsonschema.validate(
        json.loads((ROOT / "evaluation/query_registry.v2.json").read_text()), query_schema
    )
    jsonschema.validate(
        json.loads((ROOT / "evaluation/results/query-ranking-canary.v1.json").read_text()),
        ranking_schema,
    )


def test_canary_metrics_are_explicitly_closed_pool() -> None:
    visual, queries, raw = _inputs()
    result = evaluate_rankings(queries, load_ranking_artifact(raw, queries, visual))
    assert result["scope"] == "closed_judged_pool"
    assert result["metrics"] == {
        "queries": 90,
        "queries_with_results": 90,
        "coverage": 1.0,
        "ndcg_at_5": 1.0,
        "recall_at_5": 1.0,
        "map": 1.0,
        "mrr": 1.0,
        "queries_with_hard_negative_at_5": 90,
        "hard_negatives_at_5": 360,
    }
    assert set(result["by_query_type"]) == {"package", "pinout", "table"}


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("missing", "rankings missing"),
        ("duplicate_query", "duplicate ranking"),
        ("injected", "unjudged candidate"),
        ("duplicate_candidate", "duplicate candidates"),
        ("unsorted", "score-descending"),
    ],
)
def test_ranking_contract_rejects_incomplete_or_injected_results(
    mutation: str, message: str
) -> None:
    visual, queries, raw = _inputs()
    broken = deepcopy(raw)
    if mutation == "missing":
        broken["rankings"].pop()
    elif mutation == "duplicate_query":
        broken["rankings"].append(deepcopy(broken["rankings"][0]))
    elif mutation == "injected":
        broken["rankings"][0]["candidates"][0]["case_id"] = "other/unjudged"
    elif mutation == "duplicate_candidate":
        broken["rankings"][0]["candidates"][1]["case_id"] = broken["rankings"][0]["candidates"][0][
            "case_id"
        ]
    else:
        broken["rankings"][0]["candidates"][1]["score"] = 999.0
    with pytest.raises(QueryRankingError, match=message):
        load_ranking_artifact(broken, queries, visual)


def test_abstention_has_defined_zero_metrics() -> None:
    visual, queries, raw = _inputs()
    for ranking in raw["rankings"]:
        ranking["candidates"] = []
    result = evaluate_rankings(queries, load_ranking_artifact(raw, queries, visual))
    assert result["metrics"]["coverage"] == 0.0
    assert result["metrics"]["ndcg_at_5"] == 0.0
    assert result["metrics"]["map"] == 0.0
    assert result["metrics"]["mrr"] == 0.0

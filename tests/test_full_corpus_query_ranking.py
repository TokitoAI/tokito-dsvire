from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from dsvire.corpus_coverage import load_query_registry
from dsvire.query_ranking import (
    QueryRankingError,
    evaluate_full_corpus_rankings,
    full_corpus_order_sha256,
    load_full_corpus_ranking_artifact,
)
from dsvire.text_query_baseline import CandidateText, implementation_sha256, score_query_candidate
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).parents[1]


def _contracts():
    visual = load_visual_registry_data(
        json.loads((ROOT / "evaluation/visual_registry.v1.json").read_text())
    )
    queries = load_query_registry(
        json.loads((ROOT / "evaluation/query_registry.v2.json").read_text()), visual
    )
    documents = [document for document in visual.documents if document.split == "development"]
    candidate_ids = sorted(
        f"{document.document_id}/{case.case_id}"
        for document in documents
        for case in document.cases
    )
    raw = {
        "schema_version": "dsvire.full-corpus-query-ranking.v1",
        "query_registry_sha256": queries.content_sha256,
        "visual_registry_sha256": visual.content_sha256,
        "split": "development",
        "system": {"id": "test", "sha256": "a" * 64},
        "candidate_case_ids": candidate_ids,
        "rankings": [
            {
                "query_id": query.query_id,
                "candidates": [
                    {"case_id": case_id, "score": float(len(candidate_ids) - index)}
                    for index, case_id in enumerate(candidate_ids)
                ],
            }
            for query in queries.queries
            if query.split == "development"
        ],
    }
    return visual, queries, raw


def test_full_corpus_contract_and_unjudged_accounting() -> None:
    visual, queries, raw = _contracts()
    artifact = load_full_corpus_ranking_artifact(raw, queries, visual)
    result = evaluate_full_corpus_rankings(queries, artifact)
    assert result["scope"] == "complete_split_candidate_universe"
    assert result["candidate_cases"] == 209
    assert result["metrics"]["queries"] == 90
    assert result["metrics"]["judged_at_5"] + result["metrics"]["unjudged_at_5"] == 450
    assert result["metrics"]["ndcg_at_5"] == round(result["metrics"]["ndcg_at_5"], 12)


def test_full_corpus_order_digest_ignores_scores_but_binds_order() -> None:
    visual, queries, raw = _contracts()
    first = load_full_corpus_ranking_artifact(raw, queries, visual)
    score_changed = deepcopy(raw)
    score_changed["rankings"][0]["candidates"][0]["score"] += 0.00001
    second = load_full_corpus_ranking_artifact(score_changed, queries, visual)
    assert first.content_sha256 != second.content_sha256
    assert full_corpus_order_sha256(first) == full_corpus_order_sha256(second)
    order_changed = deepcopy(raw)
    candidates = order_changed["rankings"][0]["candidates"]
    first_score, second_score = candidates[0]["score"], candidates[1]["score"]
    candidates[0], candidates[1] = candidates[1], candidates[0]
    candidates[0]["score"], candidates[1]["score"] = first_score, second_score
    third = load_full_corpus_ranking_artifact(order_changed, queries, visual)
    assert full_corpus_order_sha256(first) != full_corpus_order_sha256(third)


def test_full_corpus_contract_schema_accepts_complete_artifact() -> None:
    _, _, raw = _contracts()
    schema = json.loads(
        (ROOT / "scripts/schema/full_corpus_query_ranking_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("missing_query", "every query"),
        ("duplicate_query", "duplicate ranking"),
        ("missing_candidate", "complete candidate universe"),
        ("duplicate_candidate", "duplicate candidates"),
        ("injected", "injects a candidate"),
        ("unsorted", "score-descending"),
        ("candidate_manifest", "complete sorted split universe"),
    ],
)
def test_full_corpus_contract_fails_closed(mutation: str, message: str) -> None:
    visual, queries, raw = _contracts()
    broken = deepcopy(raw)
    if mutation == "missing_query":
        broken["rankings"].pop()
    elif mutation == "duplicate_query":
        broken["rankings"].append(deepcopy(broken["rankings"][0]))
    elif mutation == "missing_candidate":
        broken["rankings"][0]["candidates"].pop()
    elif mutation == "duplicate_candidate":
        broken["rankings"][0]["candidates"][1]["case_id"] = broken["rankings"][0]["candidates"][0][
            "case_id"
        ]
    elif mutation == "injected":
        broken["rankings"][0]["candidates"][0]["case_id"] = "injected/case"
    elif mutation == "unsorted":
        broken["rankings"][0]["candidates"][1]["score"] = 99999.0
    else:
        broken["candidate_case_ids"].pop()
    with pytest.raises(QueryRankingError, match=message):
        load_full_corpus_ranking_artifact(broken, queries, visual)


def test_text_baseline_is_query_conditioned_without_labels() -> None:
    visual, queries, _ = _contracts()
    query = next(query for query in queries.queries if query.query_type == "pinout")
    document = next(document for document in visual.documents if document.split == "development")
    pinout = next(case for case in document.cases if case.region_type == "pinout")
    package = next(case for case in document.cases if case.region_type == "package")
    pin_candidate = CandidateText("pin", document, pinout, query.query_text)
    package_candidate = CandidateText("package", document, package, query.query_text)
    assert score_query_candidate(query, pin_candidate) > score_query_candidate(
        query, package_candidate
    )
    relabelled = CandidateText(
        "pin", document, replace(pinout, label="wrong_figure"), query.query_text
    )
    assert score_query_candidate(query, relabelled) == score_query_candidate(query, pin_candidate)


def test_committed_full_corpus_result_is_schema_valid_and_digest_bound() -> None:
    result = json.loads(
        (ROOT / "evaluation/results/full-corpus-text-development-2026-08-13.json").read_text()
    )
    schema = json.loads(
        (ROOT / "scripts/schema/full_corpus_text_baseline_result_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(result, schema)
    deterministic = deepcopy(result)
    deterministic.pop("runtime")
    expected = deterministic.pop("result_sha256")
    actual = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert actual == expected
    assert result["system"]["sha256"] == implementation_sha256()
    assert result["scope"] == {
        "split": "development",
        "documents": 30,
        "queries": 90,
        "candidate_cases": 209,
        "ranked_pairs": 18_810,
    }
    assert len({item["document_id"] for item in result["source"]["source_manifest"]}) == 30

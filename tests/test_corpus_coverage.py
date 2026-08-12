from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from dsvire.corpus_coverage import (
    CorpusCoverageError,
    audit_corpus_coverage,
    load_coverage_policy,
    load_query_registry,
)
from dsvire.visual_registry import load_visual_registry_data


def _inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    root = Path(__file__).parents[1]
    registry = json.loads((root / "evaluation/visual_registry.v1.json").read_text())
    policy = json.loads((root / "evaluation/corpus_coverage_policy.v1.json").read_text())
    queries = json.loads((root / "evaluation/query_registry.v2.json").read_text())
    return registry, policy, queries


def test_committed_coverage_is_deterministic_and_honest() -> None:
    registry_data, policy_data, query_data = _inputs()
    registry = load_visual_registry_data(registry_data)
    policy = load_coverage_policy(policy_data)
    queries = load_query_registry(query_data, registry)
    first = audit_corpus_coverage(registry, policy, queries)
    second = audit_corpus_coverage(registry, policy, queries)

    assert first == second
    assert first["achieved"] == {
        "documents": 40,
        "document_families": 40,
        "explicit_queries": 90,
        "annotated_cases": 279,
        "manufacturers": 14,
        "categories": 32,
    }
    assert first["remaining"] == {"documents": 460, "queries": 1910}
    assert first["target_met"] is False
    assert first["review"]["independent_human_documents"] == 0
    assert sum(first["case_labels"].values()) == 279
    assert sum(first["case_intents"].values()) == 279
    assert first["query_provenance"] == {
        "deterministic_template": 90,
        "manual": 0,
        "independently_reviewed": 0,
    }


def test_policy_rejects_overlapping_strata() -> None:
    _, policy, _ = _inputs()
    broken = deepcopy(policy)
    broken["category_strata"]["rf"].append("microcontroller")
    with pytest.raises(CorpusCoverageError, match="multiple strata"):
        load_coverage_policy(broken)


def test_audit_rejects_unassigned_registry_category() -> None:
    registry_data, policy_data, query_data = _inputs()
    broken = deepcopy(policy_data)
    broken["category_strata"]["discrete"].remove("timer")
    with pytest.raises(CorpusCoverageError, match="not assigned"):
        audit_corpus_coverage(
            load_visual_registry_data(registry_data),
            load_coverage_policy(broken),
            load_query_registry(query_data, load_visual_registry_data(registry_data)),
        )


def test_existing_registry_rejects_split_leakage() -> None:
    registry_data, _, _ = _inputs()
    leaked = deepcopy(registry_data)
    leaked["documents"][1]["document_group"] = leaked["documents"][0]["document_group"]
    leaked["documents"][1]["split"] = "evaluation"
    with pytest.raises(ValueError, match="leaks across splits"):
        load_visual_registry_data(leaked)


def test_query_registry_validates_grounding_and_changes_count() -> None:
    registry_data, policy_data, _ = _inputs()
    registry = load_visual_registry_data(registry_data)
    first = registry.documents[0]
    positive = next(case for case in first.cases if case.label == "positive")
    data = {
        "schema_version": "dsvire.query-registry.v2",
        "queries": [
            {
                "id": "q-1",
                "document_group": first.document_group,
                "split": first.split,
                "query_text": "Where is the pin map?",
                "query_type": positive.region_type,
                "relevance_judgments": [
                    {"case_id": f"{first.document_id}/{positive.case_id}", "grade": 2}
                ],
                "hard_negative_case_ids": [
                    f"{first.document_id}/{case.case_id}"
                    for case in first.cases
                    if case.label != "positive"
                ],
                "provenance": {
                    "method": "manual",
                    "generator": "test",
                    "independently_reviewed": False,
                },
            }
        ],
    }
    queries = load_query_registry(data, registry)
    result = audit_corpus_coverage(registry, load_coverage_policy(policy_data), queries)
    assert result["achieved"]["explicit_queries"] == 1
    assert result["query_intents"][positive.region_type] == 1

    data["queries"][0]["split"] = "evaluation"
    with pytest.raises(CorpusCoverageError, match="split differs"):
        load_query_registry(data, registry)


def test_development_query_tranche_is_complete_and_grounded() -> None:
    registry_data, policy_data, query_data = _inputs()
    registry = load_visual_registry_data(registry_data)
    queries = load_query_registry(query_data, registry)
    assert len(queries.queries) == 90
    assert {query.split for query in queries.queries} == {"development"}
    assert {query.query_type for query in queries.queries} == {"pinout", "table", "package"}
    assert all(query.method == "deterministic_template" for query in queries.queries)
    assert not any(query.independently_reviewed for query in queries.queries)
    result = audit_corpus_coverage(registry, load_coverage_policy(policy_data), queries)
    assert result["achieved"]["explicit_queries"] == 90
    assert result["remaining"]["queries"] == 1910
    assert result["query_intents"] == {"pinout": 30, "table": 30, "package": 30}


def test_development_query_generator_is_byte_stable(tmp_path: Path) -> None:
    import subprocess
    import sys

    root = Path(__file__).parents[1]
    output = tmp_path / "queries.json"
    subprocess.run(
        [sys.executable, "scripts/build_development_queries.py", "--out", str(output)],
        cwd=root,
        check=True,
    )
    assert output.read_bytes() == (root / "evaluation/query_registry.v2.json").read_bytes()


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("unknown_relevant", "unknown case"),
        ("duplicate_relevant", "duplicate relevance"),
        ("invalid_grade", "grade must be 1 or 2"),
        ("relevant_as_negative", "relevance and hard negatives overlap"),
        ("cross_family", "hard negatives must be non-relevant"),
        ("overlap", "relevance and hard negatives overlap"),
    ],
)
def test_query_v2_rejects_invalid_judgments_and_negatives(mutation: str, message: str) -> None:
    registry_data, _, query_data = _inputs()
    registry = load_visual_registry_data(registry_data)
    broken = deepcopy(query_data)
    query = broken["queries"][0]
    relevant = query["relevance_judgments"][0]["case_id"]
    if mutation == "unknown_relevant":
        query["relevance_judgments"][0]["case_id"] = "unknown/case"
    elif mutation == "duplicate_relevant":
        query["relevance_judgments"].append(deepcopy(query["relevance_judgments"][0]))
    elif mutation == "invalid_grade":
        query["relevance_judgments"][0]["grade"] = 3
    elif mutation == "relevant_as_negative":
        query["hard_negative_case_ids"][0] = relevant
    elif mutation == "cross_family":
        query["hard_negative_case_ids"][0] = broken["queries"][-1]["hard_negative_case_ids"][0]
    else:
        query["hard_negative_case_ids"][0] = relevant
    with pytest.raises(CorpusCoverageError, match=message):
        load_query_registry(broken, registry)

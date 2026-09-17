from __future__ import annotations

import json
from pathlib import Path

from dsvire.corpus_coverage import load_query_registry
from dsvire.cycle_eval_export import export_sealed_cycle_eval_artifacts
from dsvire.visual_registry import load_visual_registry_data
from dsvire.visual_split_plan import bind_registry_to_split_plan, load_visual_split_plan_data

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "evaluation" / name).read_text(encoding="utf-8"))


def test_cycle_v5_sealed_submission_exports_reviewed_split_registries() -> None:
    artifacts = export_sealed_cycle_eval_artifacts(
        _load("retrieval_cycle_v5_preregistration.json"),
        _load("retrieval_cycle_v5_authoring_packet.json"),
        _load("retrieval_cycle_v5_authoring_submission.json"),
        _load("retrieval_cycle_v5_authoring_seal.json"),
        _load("retrieval_cycle_v5_source_manifest.json"),
    )
    visual = load_visual_registry_data(artifacts["visual_registry"])
    queries = load_query_registry(artifacts["query_registry"], visual)
    assert len(visual.documents) == 12
    assert len(queries.queries) == 72
    assert {document.split for document in visual.documents} == {"calibration", "evaluation"}
    assert sum(query.split == "calibration" for query in queries.queries) == 36
    assert sum(query.split == "evaluation" for query in queries.queries) == 36
    intents = {query.query_type for query in queries.queries}
    assert intents == {"pinout", "table", "package"}
    for document in visual.documents:
        region_types = {case.region_type for case in document.cases}
        assert region_types <= {"pinout", "table", "package"}
        assert {"pinout", "table", "package"} <= {
            case.region_type for case in document.cases if case.label == "positive"
        }
        assert any(case.label != "positive" for case in document.cases)
    plan, _digest = load_visual_split_plan_data(artifacts["split_plan"])
    bind_registry_to_split_plan(
        load_visual_registry_data(
            {
                "schema_version": artifacts["visual_registry"]["schema_version"],
                "documents": [
                    document
                    for document in artifacts["visual_registry"]["documents"]
                    if document["split"] == "calibration"
                ],
            }
        ),
        plan,
        "calibration",
    )

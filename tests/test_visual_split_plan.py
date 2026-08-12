from __future__ import annotations

import json
import re
from pathlib import Path


def test_held_out_split_plan_is_frozen_before_scoring() -> None:
    root = Path(__file__).parents[1]
    plan = json.loads((root / "evaluation/visual_split_plan.v1.json").read_text())
    assert plan["schema_version"] == "dsvire.visual-split-plan.v1"
    assert set(plan) == {"schema_version", "created_at", "assignment_method", "families"}
    families = plan["families"]
    assert len(families) == 10
    assert len({family["id"] for family in families}) == 10
    assert {family["split"] for family in families} == {"calibration", "evaluation"}
    assert sum(family["split"] == "calibration" for family in families) == 5
    assert sum(family["split"] == "evaluation" for family in families) == 5
    assert all(family["source_url"].startswith("https://") for family in families)
    assert all(re.fullmatch(r"[0-9a-f]{64}", family["content_sha256"]) for family in families)

    registry = json.loads((root / "evaluation/visual_registry.v1.json").read_text())
    documents = {document["id"]: document for document in registry["documents"]}
    calibration = [family for family in families if family["split"] == "calibration"]
    evaluation = [family for family in families if family["split"] == "evaluation"]
    for family in calibration:
        document = documents[family["id"]]
        assert document["split"] == family["split"]
        assert document["category"] == family["category"]
        assert document["source"]["url"] == family["source_url"]
        assert document["content_sha256"] == family["content_sha256"]
        assert document["review"]["status"] == "reviewed"
    assert not set(documents).intersection(family["id"] for family in evaluation)

    result_files = list((root / "evaluation/results").glob("*.json"))
    serialized_results = "\n".join(path.read_text() for path in result_files)
    assert not any(family["id"] in serialized_results for family in evaluation)
    assert all(family["id"] in serialized_results for family in calibration)

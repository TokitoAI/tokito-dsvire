from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsvire.visual_registry import load_visual_registry_data
from dsvire.visual_split_plan import bind_registry_to_split_plan, load_visual_split_plan_data


def test_calibration_registry_is_bound_to_frozen_plan_digest() -> None:
    root = Path(__file__).parents[1]
    plan, digest = load_visual_split_plan_data(
        json.loads((root / "evaluation/visual_split_plan.v1.json").read_text())
    )
    registry_data = json.loads((root / "evaluation/visual_registry.v1.json").read_text())
    registry_data["documents"] = [
        document for document in registry_data["documents"] if document["split"] == "calibration"
    ]
    registry = load_visual_registry_data(registry_data)
    bind_registry_to_split_plan(registry, plan, "calibration")
    assert len(digest) == 64


def test_split_plan_binding_rejects_missing_family_and_source_drift() -> None:
    root = Path(__file__).parents[1]
    plan, _digest = load_visual_split_plan_data(
        json.loads((root / "evaluation/visual_split_plan.v1.json").read_text())
    )
    registry_data = json.loads((root / "evaluation/visual_registry.v1.json").read_text())
    calibration = [
        document for document in registry_data["documents"] if document["split"] == "calibration"
    ]
    missing = {"schema_version": registry_data["schema_version"], "documents": calibration[:-1]}
    with pytest.raises(ValueError, match="does not exactly match"):
        bind_registry_to_split_plan(load_visual_registry_data(missing), plan, "calibration")

    drifted = json.loads(json.dumps(calibration))
    drifted[0]["source"]["url"] = "https://example.invalid/drift.pdf"
    with pytest.raises(ValueError, match="drifted"):
        bind_registry_to_split_plan(
            load_visual_registry_data(
                {"schema_version": registry_data["schema_version"], "documents": drifted}
            ),
            plan,
            "calibration",
        )

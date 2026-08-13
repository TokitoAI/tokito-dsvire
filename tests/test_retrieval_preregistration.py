from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from dsvire.retrieval_preregistration import (
    RetrievalPreregistrationError,
    load_retrieval_preregistration,
)

ROOT = Path(__file__).parents[1]


def _plan() -> dict[str, object]:
    return json.loads((ROOT / "evaluation/retrieval_cycle_v2_preregistration.json").read_text())


def _consumed() -> set[str]:
    registry = json.loads((ROOT / "evaluation/visual_registry.v1.json").read_text())
    return {document["id"] for document in registry["documents"]} | {
        document["document_group"] for document in registry["documents"]
    }


def test_committed_cycle_is_balanced_official_and_unconsumed() -> None:
    raw = _plan()
    schema = json.loads(
        (ROOT / "scripts/schema/retrieval_preregistration_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    plan = load_retrieval_preregistration(raw, consumed_family_ids=_consumed())
    assert plan.plan_id == "dsvire-colsmol-cycle-v2@2026-08-13"
    assert plan.content_sha256 == "6acc99d5621fcd3f73efdc801b7fc7754ac244d600e94b106e6c62712116698d"
    assert len(plan.family_ids) == 12


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("overlap", "consumed"),
        ("gate", "frozen gate"),
        ("host", "official HTTPS"),
        ("balance", "six families"),
    ],
)
def test_cycle_rejects_post_registration_drift(mutation: str, message: str) -> None:
    raw = deepcopy(_plan())
    families = raw["families"]
    if mutation == "overlap":
        families[0]["id"] = next(iter(_consumed()))
    elif mutation == "gate":
        raw["frozen_gate"]["target_gpu_hot_query_p95_ms_maximum"] = 900
    elif mutation == "host":
        families[0]["official_source_url"] = "https://ti.example.com/datasheet.pdf"
    else:
        families[0]["split"] = "evaluation"
    with pytest.raises(RetrievalPreregistrationError, match=message):
        load_retrieval_preregistration(raw, consumed_family_ids=_consumed())


def test_pre_registration_contains_no_acquired_or_scored_fields() -> None:
    prohibited = {"content_sha256", "score_sha256", "bbox_norm", "page", "threshold"}

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for child in value.values() for key in keys(child)}
        if isinstance(value, list):
            return {key for child in value for key in keys(child)}
        return set()

    assert prohibited.isdisjoint(keys(_plan()))

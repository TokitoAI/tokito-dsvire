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


def _plan_v3() -> dict[str, object]:
    return json.loads((ROOT / "evaluation/retrieval_cycle_v3_preregistration.json").read_text())


def _plan_v4() -> dict[str, object]:
    return json.loads((ROOT / "evaluation/retrieval_cycle_v4_preregistration.json").read_text())


def _consumed() -> set[str]:
    registry = json.loads((ROOT / "evaluation/visual_registry.v1.json").read_text())
    return {document["id"] for document in registry["documents"]} | {
        document["document_group"] for document in registry["documents"]
    }


def _reserved() -> set[str]:
    return _consumed() | {family["id"] for family in _plan()["families"]}


def _reserved_through_v3() -> set[str]:
    return _reserved() | {family["id"] for family in _plan_v3()["families"]}


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


def test_cycle_v3_is_balanced_official_and_disjoint_from_all_prior_cycles() -> None:
    raw = _plan_v3()
    schema = json.loads(
        (ROOT / "scripts/schema/retrieval_preregistration_v1.schema.json").read_text()
    )
    jsonschema.validate(raw, schema)
    plan = load_retrieval_preregistration(raw, consumed_family_ids=_reserved())
    assert plan.plan_id == "dsvire-colsmol-egvv-cycle-v3@2026-08-13"
    assert plan.content_sha256 == "2034c81f041d547249bed9e7e606d2255af0b5df32ebfda7ad025a8c917d7ccf"
    assert len(plan.family_ids) == 12
    assert "availability_preflight" in raw["acquisition"]
    assert "independent human" in raw["annotation"]["review_protocol"]
    assert "agent audit" in raw["invalidation"][-2]


def test_cycle_v4_is_body_eligible_and_disjoint_from_every_prior_cycle() -> None:
    raw = _plan_v4()
    schema = json.loads(
        (ROOT / "scripts/schema/retrieval_preregistration_v1.schema.json").read_text()
    )
    jsonschema.validate(raw, schema)
    plan = load_retrieval_preregistration(raw, consumed_family_ids=_reserved_through_v3())
    assert plan.plan_id == "dsvire-colsmol-egvv-cycle-v4@2026-08-13"
    assert plan.content_sha256 == "cd7b1bd89d0e3d382eb7ea0af97107ca6931b3cd49a34964e18e4cef9dbb8acb"
    assert len(plan.family_ids) == 12
    preflight = raw["acquisition"]["availability_preflight"]
    assert "strict PDF parsing" in preflight and "immediately deleted" in preflight
    assert "independent human" in raw["annotation"]["review_protocol"]


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

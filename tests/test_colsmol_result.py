from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
from referencing import Registry, Resource


def test_committed_colsmol_result_is_schema_valid_and_digest_bound() -> None:
    root = Path(__file__).parents[1]
    result = json.loads(
        (root / "evaluation/results/full-corpus-colsmol-development-2026-08-13.json").read_text()
    )
    schema = json.loads(
        (root / "scripts/schema/full_corpus_colsmol_result_v1.schema.json").read_text()
    )
    text_schema_path = root / "scripts/schema/full_corpus_text_baseline_result_v1.schema.json"
    text_schema = json.loads(text_schema_path.read_text())
    resource = Resource.from_contents(text_schema)
    registry = Registry().with_resources(
        [
            (text_schema["$id"], resource),
            ("https://tokito.ai/schemas/dsvire/" + text_schema_path.name, resource),
        ]
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, registry=registry).validate(result)
    deterministic = deepcopy(result)
    deterministic.pop("runtime")
    expected = deterministic.pop("result_sha256")
    assert (
        hashlib.sha256(
            json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == expected
    )
    assert result["runtime"]["target_gpu_query"]["slo_passed"] is True
    assert result["runtime"]["independent_cpu_query"]["complete_order_match"] is True
    assert result["pack"]["naive_full_page_ratio"] is None

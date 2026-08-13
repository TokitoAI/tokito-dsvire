from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from dsvire.retrieval_pack import (
    ModelIdentity,
    RetrievalPackError,
    _canonical,
    build_retrieval_pack,
    load_retrieval_pack,
)


def _payload() -> dict[str, Any]:
    return {
        "source_sha256": "1" * 64,
        "models": {
            "dense": {"id": "dense@test", "sha256": "2" * 64},
            "multi": {"id": "multi@test", "sha256": "3" * 64},
        },
        "dense_dim": 2,
        "multi_dim": 2,
        "vector_dtype": "float32",
        "regions": [
            {
                "id": "doc/a",
                "page": 1,
                "bbox_norm": [0.1, 0.2, 0.5, 0.8],
                "type": "pinout",
                "content_sha256": "4" * 64,
                "text_fields": {"caption": "pin assignments", "pins": "VCC GND"},
                "dense": [1.0, 0.0],
                "multi": [[1.0, 0.0], [0.0, 1.0]],
            },
            {
                "id": "doc/b",
                "page": 2,
                "bbox_norm": [0.0, 0.0, 1.0, 1.0],
                "type": "package",
                "content_sha256": "5" * 64,
                "text_fields": {"caption": "package outline dimensions"},
                "dense": [0.0, 1.0],
                "multi": [[0.0, 1.0]],
            },
        ],
    }


def test_build_and_load_content_addressed_pack() -> None:
    payload = _payload()
    envelope = build_retrieval_pack(payload)
    payload["regions"][0]["dense"][0] = 99
    pack = load_retrieval_pack(envelope)
    assert pack.pack_sha256 == envelope["payload_sha256"]
    assert [region.id for region in pack.regions] == ["doc/a", "doc/b"]
    assert pack.multi_model.id == "multi@test"
    assert dict(pack.regions[0].text_fields) == {"caption": "pin assignments", "pins": "VCC GND"}
    assert pack.vector_dtype == "float32"


def test_pack_schema_accepts_canonical_envelope() -> None:
    import json

    schema = json.loads(
        (Path(__file__).parents[1] / "scripts/schema/retrieval_pack_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(build_retrieval_pack(_payload()), schema)


def test_pack_rejects_runtime_model_drift() -> None:
    envelope = build_retrieval_pack(_payload())
    with pytest.raises(RetrievalPackError, match="dense model identity mismatch"):
        load_retrieval_pack(envelope, expected_dense_model=ModelIdentity("dense@other", "9" * 64))


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("digest", "digest mismatch"),
        ("duplicate", "duplicate or unsafe"),
        ("traversal", "duplicate or unsafe"),
        ("dimension", "dimension 2"),
        ("nan", "invalid value"),
        ("bbox", "bbox_norm is invalid"),
        ("type", "type is unsupported"),
        ("order", "sorted by id"),
        ("unknown", "keys are invalid"),
        ("dtype", "vector_dtype"),
        ("bbox_text", "bbox_norm is invalid"),
        ("vector_bool", "only numbers"),
    ],
)
def test_pack_fails_closed(mutation: str, message: str) -> None:
    envelope = build_retrieval_pack(_payload())
    broken = deepcopy(envelope)
    if mutation == "digest":
        broken["payload"]["regions"][0]["text_fields"]["caption"] = "changed"
    else:
        payload = deepcopy(_payload())
        if mutation == "duplicate":
            payload["regions"][1]["id"] = "doc/a"
        elif mutation == "traversal":
            payload["regions"][0]["id"] = "../secret"
        elif mutation == "dimension":
            payload["regions"][0]["dense"] = [1.0]
        elif mutation == "nan":
            payload["regions"][0]["multi"][0][0] = float("nan")
        elif mutation == "bbox":
            payload["regions"][0]["bbox_norm"] = [0.5, 0.2, 0.1, 0.8]
        elif mutation == "type":
            payload["regions"][0]["type"] = "unknown"
        elif mutation == "order":
            payload["regions"].reverse()
        elif mutation == "unknown":
            payload["regions"][0]["label"] = "positive"
        elif mutation == "dtype":
            payload["vector_dtype"] = "float64"
        elif mutation == "bbox_text":
            payload["regions"][0]["bbox_norm"][0] = "zero"
        elif mutation == "vector_bool":
            payload["regions"][0]["dense"][0] = True
        broken = {
            "schema_version": envelope["schema_version"],
            "payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
            "payload": payload,
        }
    with pytest.raises(RetrievalPackError, match=message):
        load_retrieval_pack(broken)

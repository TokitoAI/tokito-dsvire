"""Negative tests for scripts/schema/symbol_evidence_v1.schema.json.

Every documented rule in docs/CONTRACTS.md §1 gets one test that constructs
a valid baseline document, breaks exactly the property under test, and asserts
the schema rejects it. If the tokito-catalog::pipeline::evidence Rust types
diverge from CONTRACTS.md, these tests are the first line to catch it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "scripts" / "schema" / "symbol_evidence_v1.schema.json"


BASE_VALID: dict = {
    "schema_version": "dsvire.symbol-evidence.v1",
    "datasheet": {
        "id": "ex-1",
        "content_sha256": "a" * 64,
        "manufacturer": "Example Corp",
        "mpn": "EX123",
        "package": "SOIC-8",
    },
    "regions": [
        {
            "region_id": "r_pinout_01",
            "type": "pinout",
            "page": 1,
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "crop_uri": "dsvire://fixture/ex-1/r_pinout_01.webp",
            "content_hash": "sha256:" + "b" * 64,
            "verified": True,
            "verify_confidence": 0.9,
        }
    ],
    "retrieval": {
        "index_version": "fixture@1",
        "model_ids": ["fixture"],
        "query_ids": [],
    },
}


@pytest.fixture(scope="session")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _base() -> dict:
    return copy.deepcopy(BASE_VALID)


# ----- positive baseline ---------------------------------------------------

def test_baseline_document_is_valid(validator) -> None:
    validator.validate(_base())


# ----- top-level rules -----------------------------------------------------

def test_rejects_unknown_top_level_field(validator) -> None:
    doc = _base()
    doc["junk"] = 1
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_wrong_schema_version(validator) -> None:
    doc = _base()
    doc["schema_version"] = "dsvire.symbol-evidence.v2"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_missing_schema_version(validator) -> None:
    doc = _base()
    del doc["schema_version"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_empty_regions(validator) -> None:
    doc = _base()
    doc["regions"] = []
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


# ----- datasheet -----------------------------------------------------------

def test_rejects_unknown_datasheet_field(validator) -> None:
    doc = _base()
    doc["datasheet"]["extra"] = "no"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_short_sha256(validator) -> None:
    doc = _base()
    doc["datasheet"]["content_sha256"] = "a" * 63
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_uppercase_sha256(validator) -> None:
    doc = _base()
    doc["datasheet"]["content_sha256"] = "A" * 64
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


# ----- region --------------------------------------------------------------

def test_rejects_unknown_region_field(validator) -> None:
    doc = _base()
    doc["regions"][0]["source"] = "xobject"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_region_id_without_prefix(validator) -> None:
    doc = _base()
    doc["regions"][0]["region_id"] = "pinout_01"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_bad_region_type(validator) -> None:
    doc = _base()
    doc["regions"][0]["type"] = "schematic"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_zero_page(validator) -> None:
    doc = _base()
    doc["regions"][0]["page"] = 0
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_bbox_wrong_length(validator) -> None:
    doc = _base()
    doc["regions"][0]["bbox_norm"] = [0.1, 0.2, 0.3]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_bbox_out_of_range(validator) -> None:
    doc = _base()
    doc["regions"][0]["bbox_norm"] = [-0.1, 0.1, 0.9, 0.9]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_content_hash_without_algorithm(validator) -> None:
    doc = _base()
    doc["regions"][0]["content_hash"] = "c" * 64
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_verify_confidence_over_one(validator) -> None:
    doc = _base()
    doc["regions"][0]["verify_confidence"] = 1.01
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_missing_verified_flag(validator) -> None:
    doc = _base()
    del doc["regions"][0]["verified"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_accepts_optional_caption(validator) -> None:
    doc = _base()
    doc["regions"][0]["caption"] = "Figure 1"
    validator.validate(doc)


# ----- retrieval -----------------------------------------------------------

def test_rejects_empty_model_ids(validator) -> None:
    doc = _base()
    doc["retrieval"]["model_ids"] = []
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_unknown_retrieval_field(validator) -> None:
    doc = _base()
    doc["retrieval"]["extra"] = "no"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_rejects_missing_retrieval_block(validator) -> None:
    doc = _base()
    del doc["retrieval"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)

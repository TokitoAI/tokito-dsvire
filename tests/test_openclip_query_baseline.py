from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from dsvire.openclip_query_baseline import (
    OpenClipQueryBaseline,
    OpenClipQueryError,
    _bounded_scores,
)
from dsvire.visual_adapters import OPENCLIP_MODEL_BYTES


def test_openclip_query_baseline_rejects_missing_and_wrong_size_models(tmp_path: Path) -> None:
    with pytest.raises(OpenClipQueryError, match="size"):
        OpenClipQueryBaseline(tmp_path / "missing.safetensors")
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"not a model")
    assert model.stat().st_size != OPENCLIP_MODEL_BYTES
    with pytest.raises(OpenClipQueryError, match="size"):
        OpenClipQueryBaseline(model)


def test_openclip_query_public_surface_accepts_only_raw_queries_pixels_and_model() -> None:
    init_names = OpenClipQueryBaseline.__init__.__code__.co_varnames
    rank_names = OpenClipQueryBaseline.rank.__code__.co_varnames
    assert init_names[:2] == ("self", "model_path")
    assert rank_names[:3] == ("self", "queries", "pngs")
    forbidden = {"label", "identity", "document", "case", "query_type", "package", "mpn"}
    assert forbidden.isdisjoint(init_names)
    assert forbidden.isdisjoint(rank_names)


@pytest.mark.parametrize(
    "matrix, query_count, image_count, message",
    [
        ([[0.1]], 2, 1, "matrix"),
        ([[0.1]], 1, 2, "matrix"),
        ([[float("nan")]], 1, 1, "cosine"),
        ([[float("inf")]], 1, 1, "cosine"),
        ([[1.1]], 1, 1, "cosine"),
    ],
)
def test_openclip_scores_fail_closed(
    matrix: list[list[float]], query_count: int, image_count: int, message: str
) -> None:
    with pytest.raises(OpenClipQueryError, match=message):
        _bounded_scores(matrix, query_count, image_count)


def test_openclip_scores_are_bounded_and_deterministically_rounded() -> None:
    assert _bounded_scores([[-1.0, 0.123456789, 1.0]], 1, 3) == [[0.0, 0.561728, 1.0]]


def test_committed_openclip_result_is_schema_valid_and_digest_bound() -> None:
    root = Path(__file__).parents[1]
    result = json.loads(
        (root / "evaluation/results/full-corpus-openclip-development-2026-08-13.json").read_text()
    )
    schema_path = root / "scripts/schema/full_corpus_openclip_baseline_result_v1.schema.json"
    text_schema_path = root / "scripts/schema/full_corpus_text_baseline_result_v1.schema.json"
    schema = json.loads(schema_path.read_text())
    text_schema = json.loads(text_schema_path.read_text())
    text_resource = Resource.from_contents(text_schema)
    registry = Registry().with_resources(
        [
            (text_schema["$id"], text_resource),
            (
                "https://tokito.ai/schemas/dsvire/" + text_schema_path.name,
                text_resource,
            ),
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
    assert result["scope"] == {
        "split": "development",
        "documents": 30,
        "queries": 90,
        "candidate_cases": 209,
        "ranked_pairs": 18_810,
    }

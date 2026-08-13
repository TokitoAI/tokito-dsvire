from __future__ import annotations

import math
from typing import Any

import pytest

from dsvire.hybrid_query import (
    HybridQueryError,
    hybrid_query,
    implementation_sha256,
    maxsim,
    route_types,
)
from dsvire.retrieval_pack import RetrievalPack, build_retrieval_pack, load_retrieval_pack


def _pack() -> RetrievalPack:
    payload: dict[str, Any] = {
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
                "id": "a",
                "page": 1,
                "bbox_norm": [0, 0, 1, 1],
                "type": "pinout",
                "content_sha256": "4" * 64,
                "text_fields": {"caption": "pin assignment", "pins": "VCC GND"},
                "dense": [1, 0],
                "multi": [[1, 0], [0, -1]],
            },
            {
                "id": "b",
                "page": 2,
                "bbox_norm": [0, 0, 1, 1],
                "type": "package",
                "content_sha256": "5" * 64,
                "text_fields": {"caption": "package outline dimensions"},
                "dense": [0, 1],
                "multi": [[0, 1], [-1, 0]],
            },
            {
                "id": "c",
                "page": 3,
                "bbox_norm": [0, 0, 1, 1],
                "type": "table",
                "content_sha256": "6" * 64,
                "text_fields": {"section": "electrical characteristics", "crop": "table"},
                "dense": [0.5, 0.5],
                "multi": [[-1, 0], [0, -1]],
            },
        ],
    }
    return load_retrieval_pack(build_retrieval_pack(payload))


def test_exact_maxsim_matches_scalar_reference() -> None:
    queries = [[1.0, 0.0], [0.5, 0.5]]
    documents = [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]
    reference = sum(
        max(sum(a * b for a, b in zip(q, d, strict=True)) for d in documents) for q in queries
    )
    assert maxsim(queries, documents, 2) == reference == 1.5


def test_hybrid_query_routes_fuses_and_bounds_maxsim() -> None:
    result = hybrid_query(
        _pack(),
        "show the package outline drawing",
        [0.0, 1.0],
        [[0.0, 1.0]],
        top_n=2,
        maxsim_k=2,
        limit=2,
    )
    assert result.routed_types[0] == "package"
    assert result.considered <= 3
    assert result.maxsim_evaluated == 2
    assert len(result.prefiltered_region_ids) == result.considered
    assert set(result.prefiltered_region_ids) == {"a", "b", "c"}
    assert result.hits[0].region_id == "b"
    assert all(math.isfinite(hit.score) for hit in result.hits)


def test_route_is_soft_top_two_and_deterministic() -> None:
    assert route_types("which pins and package dimensions") == ("package", "pinout")
    assert route_types("pins and package") == ("pinout", "package")
    assert route_types("unrecognized words") == ("pinout", "package")
    assert len(implementation_sha256()) == 64


@pytest.mark.parametrize(
    "query,dense,multi,top_n,maxsim_k,message",
    [
        ("", [1, 0], [[1, 0]], 2, 2, "query"),
        ("pin", [1], [[1, 0]], 2, 2, "dimension 2"),
        ("pin", [1, 0], [], 2, 2, "token limit"),
        ("pin", [1, 0], [[float("nan"), 0]], 2, 2, "invalid value"),
        ("pin", [True, 0], [[1, 0]], 2, 2, "only numbers"),
        ("pin", [1, 0], [[1, 0]], 4, 2, "top_n"),
        ("pin", [1, 0], [[1, 0]], 2, 3, "maxsim_k"),
    ],
)
def test_hybrid_query_fails_closed(
    query: str,
    dense: list[float],
    multi: list[list[float]],
    top_n: int,
    maxsim_k: int,
    message: str,
) -> None:
    with pytest.raises(HybridQueryError, match=message):
        hybrid_query(
            _pack(), query, dense, multi, top_n=top_n, maxsim_k=maxsim_k, limit=min(2, maxsim_k)
        )

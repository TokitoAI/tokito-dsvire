"""Private, digest-bound ColSmol query vectors for cross-platform reproduction."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

QUERY_VECTOR_VERSION = "dsvire.private-colsmol-query-vectors.v1"
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_QUERIES = 10_000
MAX_QUERY_TOKENS = 512
MAX_DIMENSION = 8_192


class ColSmolReproductionError(ValueError):
    """Private reproduction input is corrupt, mismatched, or outside bounds."""


@dataclass(frozen=True)
class QueryVectors:
    query_id: str
    query_text: str
    vectors: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class QueryVectorArtifact:
    content_sha256: str
    query_registry_sha256: str
    visual_registry_sha256: str
    model_id: str
    model_sha256: str
    dimension: int
    queries: tuple[QueryVectors, ...]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def build_query_vector_artifact(
    *,
    query_registry_sha256: str,
    visual_registry_sha256: str,
    model_id: str,
    model_sha256: str,
    dimension: int,
    queries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = {
        "distribution": "private; contains model-derived vectors",
        "query_registry_sha256": query_registry_sha256,
        "visual_registry_sha256": visual_registry_sha256,
        "model": {"id": model_id, "sha256": model_sha256},
        "dimension": dimension,
        "queries": list(queries),
    }
    frozen: Any = json.loads(_canonical(payload))
    envelope = {
        "schema_version": QUERY_VECTOR_VERSION,
        "payload_sha256": hashlib.sha256(_canonical(frozen)).hexdigest(),
        "payload": frozen,
    }
    load_query_vector_artifact(envelope)
    return envelope


def load_query_vector_artifact(value: Any) -> QueryVectorArtifact:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "payload_sha256",
        "payload",
    }:
        raise ColSmolReproductionError("query-vector envelope keys are invalid")
    if value["schema_version"] != QUERY_VECTOR_VERSION:
        raise ColSmolReproductionError("unsupported query-vector version")
    expected = value["payload_sha256"]
    payload = value["payload"]
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        raise ColSmolReproductionError("query-vector payload digest is invalid")
    if hashlib.sha256(_canonical(payload)).hexdigest() != expected:
        raise ColSmolReproductionError("query-vector payload digest mismatch")
    if not isinstance(payload, Mapping) or set(payload) != {
        "distribution",
        "query_registry_sha256",
        "visual_registry_sha256",
        "model",
        "dimension",
        "queries",
    }:
        raise ColSmolReproductionError("query-vector payload keys are invalid")
    if payload["distribution"] != "private; contains model-derived vectors":
        raise ColSmolReproductionError("query-vector distribution policy is invalid")
    registry_digests = (
        payload["query_registry_sha256"],
        payload["visual_registry_sha256"],
    )
    if any(
        not isinstance(item, str) or SHA256.fullmatch(item) is None for item in registry_digests
    ):
        raise ColSmolReproductionError("query-vector registry digest is invalid")
    model = payload["model"]
    if (
        not isinstance(model, Mapping)
        or set(model) != {"id", "sha256"}
        or not isinstance(model["id"], str)
        or not model["id"].strip()
        or not isinstance(model["sha256"], str)
        or SHA256.fullmatch(model["sha256"]) is None
    ):
        raise ColSmolReproductionError("query-vector model identity is invalid")
    dimension = payload["dimension"]
    if (
        isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or not 1 <= dimension <= MAX_DIMENSION
    ):
        raise ColSmolReproductionError("query-vector dimension is invalid")
    raw_queries = payload["queries"]
    if not isinstance(raw_queries, list) or not 1 <= len(raw_queries) <= MAX_QUERIES:
        raise ColSmolReproductionError("query-vector query count is invalid")
    queries: list[QueryVectors] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_queries):
        context = f"queries[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {"query_id", "query_text", "vectors"}:
            raise ColSmolReproductionError(f"{context} keys are invalid")
        query_id, query_text, vectors = raw["query_id"], raw["query_text"], raw["vectors"]
        if (
            not isinstance(query_id, str)
            or not query_id
            or query_id in seen
            or not isinstance(query_text, str)
            or not query_text.strip()
        ):
            raise ColSmolReproductionError(f"{context} identity is invalid")
        seen.add(query_id)
        if not isinstance(vectors, list) or not 1 <= len(vectors) <= MAX_QUERY_TOKENS:
            raise ColSmolReproductionError(f"{context}.vectors are outside token bounds")
        parsed: list[tuple[float, ...]] = []
        for row in vectors:
            if not isinstance(row, list) or len(row) != dimension:
                raise ColSmolReproductionError(f"{context}.vectors have invalid shape")
            vector = tuple(float(item) for item in row)
            if any(
                isinstance(item, bool) or not isinstance(item, (int, float)) for item in row
            ) or not all(math.isfinite(item) and abs(item) <= 1_000_000 for item in vector):
                raise ColSmolReproductionError(f"{context}.vectors contain invalid values")
            parsed.append(vector)
        queries.append(QueryVectors(query_id, query_text, tuple(parsed)))
    if [query.query_id for query in queries] != sorted(seen):
        raise ColSmolReproductionError("queries must be sorted by id")
    return QueryVectorArtifact(
        expected,
        registry_digests[0],
        registry_digests[1],
        model["id"].strip(),
        model["sha256"],
        dimension,
        tuple(queries),
    )

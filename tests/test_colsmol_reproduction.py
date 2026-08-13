from __future__ import annotations

from copy import deepcopy

import pytest

from dsvire.colsmol_reproduction import (
    ColSmolReproductionError,
    build_query_vector_artifact,
    load_query_vector_artifact,
)


def _artifact() -> dict[str, object]:
    return build_query_vector_artifact(
        query_registry_sha256="1" * 64,
        visual_registry_sha256="2" * 64,
        model_id="model@revision",
        model_sha256="3" * 64,
        dimension=2,
        queries=[{"query_id": "q1", "query_text": "show pins", "vectors": [[0.1, 0.2]]}],
    )


def test_private_query_vector_artifact_is_digest_and_model_bound() -> None:
    artifact = load_query_vector_artifact(_artifact())
    assert artifact.dimension == 2
    assert artifact.model_sha256 == "3" * 64
    assert artifact.queries[0].vectors == ((0.1, 0.2),)


def test_private_query_vector_artifact_rejects_tampering() -> None:
    raw = deepcopy(_artifact())
    raw["payload"]["queries"][0]["vectors"][0][0] = 0.9  # type: ignore[index]
    with pytest.raises(ColSmolReproductionError, match="digest mismatch"):
        load_query_vector_artifact(raw)

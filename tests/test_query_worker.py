from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from dsvire.query_worker import QueryRejected, execute_query, run_query_job
from dsvire.retrieval_pack import build_retrieval_pack
from dsvire.worker import WorkerLimits


def _install_pack(root: Path) -> tuple[str, dict[str, Any]]:
    envelope = build_retrieval_pack(
        {
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
                    "id": "region/a",
                    "page": 3,
                    "bbox_norm": [0.1, 0.2, 0.8, 0.9],
                    "type": "pinout",
                    "content_sha256": "4" * 64,
                    "text_fields": {"caption": "pin assignment", "pins": "VCC GND"},
                    "dense": [1, 0],
                    "multi": [[1, 0]],
                }
            ],
        }
    )
    directory = root / "retrieval-packs"
    directory.mkdir()
    digest = envelope["payload_sha256"]
    (directory / f"{digest}.json").write_text(json.dumps(envelope), encoding="utf-8")
    request = {
        "pack_sha256": digest,
        "models": envelope["payload"]["models"],
        "query": "show the pinout",
        "dense_vector": [1, 0],
        "multi_vectors": [[1, 0]],
    }
    return digest, request


def test_query_is_content_addressed_model_bound_and_provenance_rich(tmp_path: Path) -> None:
    digest, request = _install_pack(tmp_path)
    result = execute_query(tmp_path, request)
    root = Path(__file__).parents[1]
    request_schema = json.loads(
        (root / "scripts/schema/hybrid_query_request_v1.schema.json").read_text()
    )
    result_schema = json.loads(
        (root / "scripts/schema/hybrid_query_result_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(request_schema)
    jsonschema.Draft202012Validator.check_schema(result_schema)
    jsonschema.validate(request, request_schema)
    jsonschema.validate(result, result_schema)
    assert result["pack_sha256"] == digest
    assert result["source_sha256"] == "1" * 64
    assert result["models"] == request["models"]
    assert result["hits"] == [
        {
            "region_id": "region/a",
            "page": 3,
            "type": "pinout",
            "content_sha256": "4" * 64,
            "bbox_norm": [0.1, 0.2, 0.8, 0.9],
            "score": 1.0,
            "bm25_score": 0.0,
            "dense_score": 1.0,
            "maxsim_score": 1.0,
        }
    ]


@pytest.mark.parametrize("mutation", ["address", "model", "tamper", "unknown", "traversal"])
def test_query_fails_closed_on_untrusted_boundary(tmp_path: Path, mutation: str) -> None:
    digest, request = _install_pack(tmp_path)
    if mutation == "address":
        request["pack_sha256"] = "9" * 64
    elif mutation == "model":
        request["models"]["multi"]["sha256"] = "9" * 64
    elif mutation == "tamper":
        path = tmp_path / "retrieval-packs" / f"{digest}.json"
        path.write_text(path.read_text().replace("pin assignment", "changed"), encoding="utf-8")
    elif mutation == "unknown":
        request["authorization"] = "not allowed"
    elif mutation == "traversal":
        request["pack_sha256"] = "../secret"
    with pytest.raises(QueryRejected):
        execute_query(tmp_path, request)


def test_query_rejects_symlinked_pack(tmp_path: Path) -> None:
    digest, request = _install_pack(tmp_path)
    path = tmp_path / "retrieval-packs" / f"{digest}.json"
    target = tmp_path / "outside.json"
    path.replace(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(QueryRejected, match="unavailable"):
        execute_query(tmp_path, request)


def test_query_runs_in_killable_subprocess_and_cleans_scratch(tmp_path: Path) -> None:
    _digest, request = _install_pack(tmp_path)
    result = asyncio.run(
        run_query_job(
            json.dumps(request).encode(),
            tmp_path,
            timeout_seconds=5,
            limits=WorkerLimits(
                cpu_seconds=4,
                memory_bytes=1536 * 1024 * 1024,
                file_bytes=64 * 1024 * 1024,
            ),
        )
    )
    assert result["hits"][0]["region_id"] == "region/a"
    assert list((tmp_path / "query-jobs").iterdir()) == []

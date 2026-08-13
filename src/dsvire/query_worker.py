"""Killable, content-addressed query worker for untrusted packs and vectors."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .hybrid_query import HybridQueryError, hybrid_query
from .retrieval_pack import ModelIdentity, RetrievalPack, RetrievalPackError, load_retrieval_pack
from .worker import WorkerError, WorkerLimits, WorkerTimeout, _apply_resource_limits, _terminate


class QueryRejected(ValueError):
    """The query or referenced pack failed its public validation contract."""


def _strict_model(value: Any, context: str) -> ModelIdentity:
    if not isinstance(value, Mapping) or set(value) != {"id", "sha256"}:
        raise QueryRejected(f"{context} must contain only id and sha256")
    model_id, sha256 = value["id"], value["sha256"]
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id.encode()) > 512:
        raise QueryRejected(f"{context}.id is invalid")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(c not in "0123456789abcdef" for c in sha256)
    ):
        raise QueryRejected(f"{context}.sha256 is invalid")
    return ModelIdentity(model_id.strip(), sha256)


def _read_pack(data_dir: Path, digest: Any) -> bytes:
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise QueryRejected("pack_sha256 is invalid")
    root = (data_dir / "retrieval-packs").resolve()
    candidate = root / f"{digest}.json"
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise QueryRejected("retrieval pack is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 512 * 1024 * 1024:
            raise QueryRejected("retrieval pack exceeds its file or type limit")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(512 * 1024 * 1024 + 1)
    finally:
        os.close(descriptor)


def _load_pack(
    data_dir: Path, digest: Any, dense_model: ModelIdentity, multi_model: ModelIdentity
) -> RetrievalPack:
    raw = _read_pack(data_dir, digest)
    if len(raw) > 512 * 1024 * 1024:
        raise QueryRejected("retrieval pack exceeds its file limit")
    try:
        envelope = json.loads(raw)
        pack = load_retrieval_pack(
            envelope, expected_dense_model=dense_model, expected_multi_model=multi_model
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, RetrievalPackError) as exc:
        raise QueryRejected("retrieval pack failed integrity or compatibility validation") from exc
    if pack.pack_sha256 != digest:
        raise QueryRejected("retrieval pack address does not match its payload digest")
    return pack


def execute_query(data_dir: Path, request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise QueryRejected("query request must be an object")
    required = {"pack_sha256", "models", "query", "dense_vector", "multi_vectors"}
    optional = {"top_n", "maxsim_k", "limit"}
    if not required <= set(request) or not set(request) <= required | optional:
        raise QueryRejected("query request keys are invalid")
    models = request["models"]
    if not isinstance(models, Mapping) or set(models) != {"dense", "multi"}:
        raise QueryRejected("models must contain only dense and multi")
    dense_model = _strict_model(models["dense"], "models.dense")
    multi_model = _strict_model(models["multi"], "models.multi")
    pack = _load_pack(data_dir, request["pack_sha256"], dense_model, multi_model)
    try:
        result = hybrid_query(
            pack,
            request["query"],
            request["dense_vector"],
            request["multi_vectors"],
            top_n=request.get("top_n", min(100, len(pack.regions))),
            maxsim_k=request.get("maxsim_k", min(32, len(pack.regions))),
            limit=request.get("limit", min(5, len(pack.regions))),
        )
    except (HybridQueryError, TypeError) as exc:
        raise QueryRejected("query vectors or bounds are invalid") from exc
    by_id = {region.id: region for region in pack.regions}
    return {
        "schema_version": "dsvire.hybrid-query-result.v1",
        "pack_sha256": pack.pack_sha256,
        "source_sha256": pack.source_sha256,
        "models": {
            "dense": {"id": pack.dense_model.id, "sha256": pack.dense_model.sha256},
            "multi": {"id": pack.multi_model.id, "sha256": pack.multi_model.sha256},
        },
        "routed_types": list(result.routed_types),
        "considered": result.considered,
        "maxsim_evaluated": result.maxsim_evaluated,
        "hits": [
            {
                "region_id": hit.region_id,
                "page": by_id[hit.region_id].page,
                "type": by_id[hit.region_id].region_type,
                "content_sha256": by_id[hit.region_id].content_sha256,
                "bbox_norm": list(by_id[hit.region_id].bbox_norm),
                "score": hit.score,
                "bm25_score": hit.bm25_score,
                "dense_score": hit.dense_score,
                "maxsim_score": hit.maxsim_score,
            }
            for hit in result.hits
        ],
    }


def _query_worker_main(
    data_dir: Path, request_path: Path, result_path: Path, limits: WorkerLimits
) -> None:
    _apply_resource_limits(limits)
    try:
        result = execute_query(data_dir, json.loads(request_path.read_text(encoding="utf-8")))
        payload: dict[str, Any] = {"status": "ok", "result": result}
    except (QueryRejected, UnicodeError, json.JSONDecodeError, RecursionError):
        payload = {"status": "rejected"}
    except BaseException as exc:
        payload = {"status": "worker_error", "detail": type(exc).__name__}
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, result_path)


async def run_query_job(
    request_bytes: bytes,
    data_dir: Path,
    *,
    timeout_seconds: float,
    limits: WorkerLimits,
) -> dict[str, Any]:
    jobs_dir = data_dir / "query-jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="query-", dir=jobs_dir) as directory:
        request_path, result_path = (
            Path(directory) / "request.json",
            Path(directory) / "result.json",
        )
        request_path.write_bytes(request_bytes)
        process = multiprocessing.get_context("spawn").Process(
            target=_query_worker_main,
            args=(data_dir, request_path, result_path, limits),
            name="dsvire-query-worker",
        )
        process.start()
        try:
            await asyncio.wait_for(asyncio.to_thread(process.join), timeout_seconds)
        except TimeoutError as exc:
            _terminate(process)
            raise WorkerTimeout("query worker timed out") from exc
        except asyncio.CancelledError:
            _terminate(process)
            raise
        finally:
            if process.is_alive():
                _terminate(process)
        if process.exitcode != 0 or not result_path.is_file():
            raise WorkerError("query worker failed")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkerError("query worker returned an invalid result") from exc
        if payload.get("status") == "rejected":
            raise QueryRejected("query or pack failed validation")
        if payload.get("status") != "ok" or not isinstance(payload.get("result"), dict):
            raise WorkerError("query worker failed")
        return cast(dict[str, Any], payload["result"])

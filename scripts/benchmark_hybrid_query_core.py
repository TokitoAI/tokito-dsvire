#!/usr/bin/env python3
"""Deterministic dependency-light capacity evidence for the hybrid query core."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

from dsvire.corpus_coverage import load_query_registry
from dsvire.hybrid_query import SYSTEM_ID, hybrid_query, implementation_sha256
from dsvire.retrieval_pack import build_retrieval_pack, load_retrieval_pack
from dsvire.visual_registry import load_visual_registry_data

SCHEMA_VERSION = "dsvire.hybrid-query-core-benchmark.v1"


def _vector(seed: int, dimension: int) -> list[float]:
    values = [math.sin((seed + 1) * (index + 1) * 0.017) for index in range(dimension)]
    norm = math.sqrt(math.fsum(value * value for value in values))
    return [value / norm for value in values]


def _contracts(
    root: Path,
) -> tuple[list[tuple[str, int, tuple[float, float, float, float], str, str]], list[str]]:
    visual = load_visual_registry_data(
        json.loads((root / "evaluation/visual_registry.v1.json").read_text())
    )
    query_registry = load_query_registry(
        json.loads((root / "evaluation/query_registry.v2.json").read_text()), visual
    )
    cases = sorted(
        (
            f"{document.document_id}/{case.case_id}",
            case.page,
            case.bbox_norm,
            case.region_type,
            document.content_sha256,
        )
        for document in visual.documents
        if document.split == "development"
        for case in document.cases
    )
    queries = [query.query_text for query in query_registry.queries if query.split == "development"]
    return cases, queries


def _payload(
    cases: list[tuple[str, int, tuple[float, float, float, float], str, str]],
    dimension: int,
    patches: int,
) -> dict[str, Any]:
    return {
        "source_sha256": hashlib.sha256(b"deterministic-capacity-fixture-v1").hexdigest(),
        "models": {
            "dense": {"id": "capacity-fixture-dense@1", "sha256": "1" * 64},
            "multi": {"id": "capacity-fixture-multi@1", "sha256": "2" * 64},
        },
        "dense_dim": dimension,
        "multi_dim": dimension,
        "vector_dtype": "float32",
        "regions": [
            {
                "id": case_id,
                "page": page,
                "bbox_norm": list(bbox),
                "type": region_type,
                "content_sha256": hashlib.sha256(
                    f"{document_sha256}/{case_id}".encode()
                ).hexdigest(),
                "text_fields": {
                    "caption": f"{region_type} evidence region {index}",
                    "pins": "VCC GND SDA SCL" if region_type == "pinout" else "",
                },
                "dense": _vector(index, dimension),
                "multi": [
                    _vector(index * patches + patch + 10_000, dimension) for patch in range(patches)
                ],
            }
            for index, (case_id, page, bbox, region_type, document_sha256) in enumerate(cases)
        ],
    }


def _percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimension", type=int, default=32)
    parser.add_argument("--patches", type=int, default=16)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--maxsim-k", type=int, default=32)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if min(args.dimension, args.patches) < 1:
        parser.error("all cardinalities must be positive")
    root = Path(__file__).parents[1]
    cases, queries = _contracts(root)
    regions, query_count = len(cases), len(queries)
    started = time.perf_counter()
    tracemalloc.start()
    envelope = build_retrieval_pack(_payload(cases, args.dimension, args.patches))
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    pack = load_retrieval_pack(envelope)
    durations: list[float] = []
    order: list[list[str]] = []
    for index, query in enumerate(queries):
        before = time.perf_counter()
        query_result = hybrid_query(
            pack,
            query,
            _vector(index + 50_000, args.dimension),
            [_vector(index * 4 + token + 60_000, args.dimension) for token in range(4)],
            top_n=min(args.top_n, regions),
            maxsim_k=min(args.maxsim_k, args.top_n, regions),
            limit=min(5, args.maxsim_k, args.top_n, regions),
        )
        durations.append((time.perf_counter() - before) * 1000)
        order.append([hit.region_id for hit in query_result.hits])
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    semantic = {
        "schema_version": SCHEMA_VERSION,
        "system": {"id": SYSTEM_ID, "sha256": implementation_sha256()},
        "scope": {
            "regions": regions,
            "queries": query_count,
            "dimension": args.dimension,
            "patches_per_region": args.patches,
            "top_n": min(args.top_n, regions),
            "maxsim_k": min(args.maxsim_k, args.top_n, regions),
        },
        "pack": {
            "payload_sha256": pack.pack_sha256,
            "serialized_bytes": len(encoded),
            "bytes_per_region": round(len(encoded) / regions, 3),
        },
        "order_sha256": hashlib.sha256(
            json.dumps(order, separators=(",", ":")).encode()
        ).hexdigest(),
        "limitations": [
            "deterministic synthetic vectors measure query-core correctness and capacity, not retrieval accuracy",
            "encoder, vector database, network, verification, and cold pack download are excluded",
        ],
    }
    result: dict[str, Any] = {
        **semantic,
        "query": {
            "mean_ms": round(statistics.fmean(durations), 6),
            "p95_ms": round(_percentile(durations, 0.95), 6),
            "max_ms": round(max(durations), 6),
        },
        "runtime": {
            "python": platform.python_version(),
            "os": platform.system(),
            "machine": platform.machine(),
            "total_seconds": round(time.perf_counter() - started, 6),
            "traced_peak_bytes": peak_bytes,
            "pid": os.getpid(),
        },
    }
    result["result_sha256"] = hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(output)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Assemble compact public ColSmol evidence from validated private run outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

SYSTEM_ID = "dsvire.query-baseline.colsmol-hybrid@1.1.0"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-evidence", type=Path, required=True)
    parser.add_argument("--optimized-evidence", type=Path, required=True)
    parser.add_argument("--linux-reproduction", type=Path, required=True)
    parser.add_argument("--pack-json", type=Path, required=True)
    parser.add_argument("--pack-zstd", type=Path, required=True)
    parser.add_argument("--system-sha256", required=True)
    parser.add_argument("--ranking-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if len(args.system_sha256) != 64 or len(args.ranking_sha256) != 64:
        parser.error("system and ranking SHA-256 values must be complete")
    index = _read(args.index_evidence)
    optimized = _read(args.optimized_evidence)
    linux = _read(args.linux_reproduction)
    if len({index["pack_sha256"], optimized["pack_sha256"], linux["pack_sha256"]}) != 1:
        parser.error("pack identities differ")
    if (
        index["metrics"] != optimized["metrics"]
        or index["by_query_type"] != optimized["by_query_type"]
    ):
        parser.error("optimized metrics differ from the scalar reference")
    if not linux["comparison"]["complete_order_match"]:
        parser.error("independent Linux complete order differs")
    deterministic = {
        "schema_version": "dsvire.full-corpus-colsmol-result.v1",
        "source": index["source"],
        "system": {"id": SYSTEM_ID, "sha256": args.system_sha256},
        "pack": {
            "payload_sha256": index["pack_sha256"],
            "canonical_json_bytes": index["runtime"]["pack_bytes"],
            "serialized_json_bytes": args.pack_json.stat().st_size,
            "zstd_level_10_bytes": args.pack_zstd.stat().st_size,
            "zstd_level_10_sha256": _sha(args.pack_zstd),
            "naive_full_page_ratio": None,
        },
        "ranking_sha256": args.ranking_sha256,
        "scope": index["scope"],
        "metrics": index["metrics"],
        "by_query_type": index["by_query_type"],
        "limitations": index["limitations"]
        + [
            "target GPU passes the hot-query SLO; independent CPU reproduction does not",
            "compressed pack size is measured, but the naive full-page comparison is unavailable",
            "private pack, source documents, crops, model bytes, rankings, and vectors are not published",
        ],
    }
    deterministic["result_sha256"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result = {
        **deterministic,
        "runtime": {
            "indexing": {
                "total_seconds": index["runtime"]["total_seconds"],
                "image_encode_mean_ms": index["runtime"]["image_encode_mean_ms"],
                "image_encode_p95_ms": index["runtime"]["image_encode_p95_ms"],
                "query_encode_mean_ms": index["runtime"]["query_encode_mean_ms"],
                "peak_process_rss_bytes": index["runtime"]["peak_rss_bytes"],
            },
            "target_gpu_query": {
                "hot_query_mean_ms": round(optimized["runtime"]["hot_query_mean_ms"], 3),
                "hot_query_p95_ms": round(optimized["runtime"]["hot_query_p95_ms"], 3),
                "slo_ms": 800,
                "slo_passed": optimized["runtime"]["hot_query_p95_ms"] <= 800,
                "environment": {
                    "os": "Windows",
                    "python": "3.11.9",
                    "device": "NVIDIA GeForce GTX 1650",
                    "device_memory_bytes": 4_294_639_616,
                    "compute_capability": "7.5",
                    "torch": "2.13.0+cu130",
                    "torchvision": "0.28.0+cu130",
                    "transformers": "5.5.0",
                    "cuda": "13.0",
                },
            },
            "independent_cpu_query": {
                **linux["runtime"],
                "complete_order_match": True,
                "mismatched_queries": 0,
                "score_observations_sha256": linux["score_observations_sha256"],
                "cross_platform_score_comparison": linux["cross_platform_score_comparison"],
            },
            "external_cost_usd": 0.0,
        },
    }
    # Runtime observations do not alter the semantic result identity.
    check = deepcopy(result)
    check.pop("runtime")
    expected = check.pop("result_sha256")
    if (
        hashlib.sha256(
            json.dumps(check, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != expected
    ):
        raise AssertionError("result digest construction failed")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

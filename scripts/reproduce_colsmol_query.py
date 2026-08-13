"""Recompute complete ColSmol hybrid rankings from private pack/vector inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

from dsvire.colsmol_reproduction import load_query_vector_artifact
from dsvire.hybrid_query import hybrid_query, maxsim_numpy
from dsvire.retrieval_pack import ModelIdentity, load_retrieval_pack


def _mean(vectors: tuple[tuple[float, ...], ...]) -> list[float]:
    import math

    result = [
        math.fsum(row[index] for row in vectors) / len(vectors) for index in range(len(vectors[0]))
    ]
    norm = math.sqrt(math.fsum(item * item for item in result))
    return [item / norm for item in result]


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--query-vectors", type=Path, required=True)
    parser.add_argument("--reference-ranking", type=Path, required=True)
    parser.add_argument("--reference-scores", type=Path)
    parser.add_argument(
        "--private-scores-out",
        type=Path,
        help="private per-candidate MaxSim observations; never publish",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    vectors = load_query_vector_artifact(json.loads(args.query_vectors.read_text(encoding="utf-8")))
    identity = ModelIdentity(vectors.model_id, vectors.model_sha256)
    pack = load_retrieval_pack(
        json.loads(args.pack.read_text(encoding="utf-8")),
        expected_dense_model=identity,
        expected_multi_model=identity,
    )
    reference = json.loads(args.reference_ranking.read_text(encoding="utf-8"))
    if (
        reference.get("query_registry_sha256") != vectors.query_registry_sha256
        or reference.get("visual_registry_sha256") != vectors.visual_registry_sha256
        or reference.get("candidate_case_ids") != [region.id for region in pack.regions]
    ):
        parser.error("reference ranking differs from the private inputs")
    reference_by_id = {item["query_id"]: item for item in reference["rankings"]}
    timings: list[float] = []
    score_rows = []
    reproduced_orders: dict[str, list[str]] = {}
    for query in vectors.queries:
        tick = time.perf_counter()
        result = hybrid_query(
            pack,
            query.query_text,
            _mean(query.vectors),
            query.vectors,
            top_n=len(pack.regions),
            maxsim_k=min(32, len(pack.regions)),
            limit=min(32, len(pack.regions)),
            maxsim_scorer=maxsim_numpy,
        )
        timings.append((time.perf_counter() - tick) * 1000)
        rescored = {hit.region_id for hit in result.hits}
        reproduced_orders[query.query_id] = [hit.region_id for hit in result.hits] + [
            region_id for region_id in result.prefiltered_region_ids if region_id not in rescored
        ]
        score_rows.append(
            {
                "query_id": query.query_id,
                "top32": [
                    {"case_id": hit.region_id, "maxsim": round(hit.maxsim_score, 12)}
                    for hit in result.hits
                ],
            }
        )
    expected_orders = {
        query_id: [item["case_id"] for item in ranking["candidates"]]
        for query_id, ranking in reference_by_id.items()
    }
    mismatches = sorted(
        query_id
        for query_id, order in reproduced_orders.items()
        if order != expected_orders.get(query_id)
    )
    score_comparison: dict[str, Any] | None = None
    if args.reference_scores is not None:
        reference_scores = _read_private_scores(args.reference_scores)
        observed = _score_map(score_rows)
        expected_scores = _score_map(reference_scores)
        if set(observed) != set(expected_scores):
            parser.error("reference score keys differ")
        differences = [abs(observed[key] - expected_scores[key]) for key in observed]
        score_comparison = {
            "compared_scores": len(differences),
            "changed_scores": sum(value != 0 for value in differences),
            "maximum_absolute_difference": max(differences, default=0.0),
        }
    evidence = {
        "schema_version": "dsvire.colsmol-query-reproduction.v1",
        "pack_sha256": pack.pack_sha256,
        "query_vectors_sha256": vectors.content_sha256,
        "reference_ranking_file_sha256": hashlib.sha256(
            args.reference_ranking.read_bytes()
        ).hexdigest(),
        "complete_order_sha256": _digest(reproduced_orders),
        "score_observations_sha256": _digest(score_rows),
        "cross_platform_score_comparison": score_comparison,
        "scope": {
            "queries": len(vectors.queries),
            "candidate_cases": len(pack.regions),
            "ranked_pairs": len(vectors.queries) * len(pack.regions),
        },
        "comparison": {"complete_order_match": not mismatches, "mismatched_query_ids": mismatches},
        "runtime": {
            "hot_query_mean_ms": round(statistics.fmean(timings), 3),
            "hot_query_p95_ms": round(sorted(timings)[round((len(timings) - 1) * 0.95)], 3),
            "total_seconds": round(time.perf_counter() - started, 6),
            "environment": {
                "os": platform.system(),
                "os_release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "numpy": version("numpy"),
            },
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.private_scores_out is not None:
        args.private_scores_out.parent.mkdir(parents=True, exist_ok=True)
        args.private_scores_out.write_text(
            json.dumps(
                {
                    "schema_version": "dsvire.private-colsmol-score-observations.v1",
                    "distribution": "private; contains model-derived scores",
                    "sha256": _digest(score_rows),
                    "scores": score_rows,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    if mismatches:
        parser.error(f"complete ranking differs for {len(mismatches)} queries")
    return 0


def _read_private_scores(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "distribution", "sha256", "scores"}
        or value["schema_version"] != "dsvire.private-colsmol-score-observations.v1"
        or value["distribution"] != "private; contains model-derived scores"
        or not isinstance(value["scores"], list)
        or _digest(value["scores"]) != value["sha256"]
    ):
        raise ValueError("private score observations are invalid")
    return cast(list[dict[str, Any]], value["scores"])


def _score_map(rows: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for row in rows:
        query_id = str(row["query_id"])
        for item in cast(list[dict[str, Any]], row["top32"]):
            result[(query_id, str(item["case_id"]))] = float(item["maxsim"])
    return result


if __name__ == "__main__":
    raise SystemExit(main())

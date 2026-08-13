"""Build a genuine ColSmol pack and rank the complete development corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import pymupdf
from PIL import Image

from dsvire.colsmol_encoder import ColSmolEncoder
from dsvire.colsmol_reproduction import build_query_vector_artifact
from dsvire.corpus_coverage import load_query_registry
from dsvire.eval_sources import resolve_registered_sources
from dsvire.hybrid_query import hybrid_query, implementation_sha256, maxsim_numpy
from dsvire.model_manifest import load_model_manifest
from dsvire.query_ranking import (
    evaluate_full_corpus_rankings,
    full_corpus_order_sha256,
    load_full_corpus_ranking_artifact,
)
from dsvire.retrieval_pack import ModelIdentity, build_retrieval_pack, load_retrieval_pack
from dsvire.text_query_baseline import extract_candidate_text
from dsvire.visual_adapters import render_registered_crop
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ID = "dsvire.query-baseline.colsmol-hybrid@1.1.0"


def _mean(vectors: tuple[tuple[float, ...], ...]) -> list[float]:
    dimension = len(vectors[0])
    result = [math.fsum(row[index] for row in vectors) / len(vectors) for index in range(dimension)]
    norm = math.sqrt(math.fsum(item * item for item in result))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("ColSmol mean-pooled dense vector has invalid norm")
    return [item / norm for item in result]


def run(
    registry_path: Path,
    query_path: Path,
    manifest_path: Path,
    model_root: Path,
    cache_roots: list[Path],
    *,
    device: str,
    download_cache: Path | None = None,
    offline: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    visual = load_visual_registry_data(json.loads(registry_path.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(query_path.read_text(encoding="utf-8")), visual)
    manifest = load_model_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    documents = tuple(item for item in visual.documents if item.split == "development")
    selected_queries = tuple(item for item in queries.queries if item.split == "development")
    sources = resolve_registered_sources(cache_roots, documents, download_cache, offline)
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak_rss
        while not stop.wait(0.01):
            peak_rss = max(peak_rss, process.memory_info().rss)

    sampler = threading.Thread(target=sample, name="colsmol-rss", daemon=True)
    sampler.start()
    started = time.perf_counter()
    source_manifest: list[dict[str, Any]] = []
    encode_image_ms: list[float] = []
    encode_query_ms: list[float] = []
    regions: list[dict[str, Any]] = []
    try:
        encoder = ColSmolEncoder(manifest, model_root, device=device)
        for document in documents:
            payload = sources[document.content_sha256].read_bytes()
            if hashlib.sha256(payload).hexdigest() != document.content_sha256:
                raise ValueError(f"source changed while reading: {document.document_id}")
            source_manifest.append(
                {
                    "document_id": document.document_id,
                    "content_sha256": document.content_sha256,
                    "bytes": len(payload),
                }
            )
            with pymupdf.open(stream=payload, filetype="pdf") as pdf:
                for case in document.cases:
                    png = render_registered_crop(pdf, case)
                    tick = time.perf_counter()
                    with Image.open(__import__("io").BytesIO(png)) as raw_image:
                        image = raw_image.convert("RGB")
                        multi = encoder.encode_images([image])[0]
                    encode_image_ms.append((time.perf_counter() - tick) * 1000)
                    regions.append(
                        {
                            "id": f"{document.document_id}/{case.case_id}",
                            "page": case.page,
                            "bbox_norm": list(case.bbox_norm),
                            "type": case.region_type,
                            "content_sha256": hashlib.sha256(png).hexdigest(),
                            "text_fields": {"crop": extract_candidate_text(pdf, document, case)},
                            "dense": _mean(multi),
                            "multi": [list(token) for token in multi],
                        }
                    )
        query_vectors: dict[str, tuple[tuple[float, ...], ...]] = {}
        for query in selected_queries:
            tick = time.perf_counter()
            query_vectors[query.query_id] = encoder.encode_queries([query.query_text])[0]
            encode_query_ms.append((time.perf_counter() - tick) * 1000)
        corpus_sha = hashlib.sha256(
            json.dumps(source_manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        model_identity = {"id": encoder.model_id, "sha256": encoder.model_sha256}
        pack_raw = build_retrieval_pack(
            {
                "source_sha256": corpus_sha,
                "models": {"dense": model_identity, "multi": model_identity},
                "dense_dim": encoder.dimension,
                "multi_dim": encoder.dimension,
                "vector_dtype": "float32",
                "regions": sorted(regions, key=lambda item: str(item["id"])),
            }
        )
        identity = ModelIdentity(encoder.model_id, encoder.model_sha256)
        pack = load_retrieval_pack(
            pack_raw, expected_dense_model=identity, expected_multi_model=identity
        )
        system_sha = hashlib.sha256(
            f"{encoder.implementation_sha256}\n{implementation_sha256()}".encode()
        ).hexdigest()
        rankings = []
        query_ms: list[float] = []
        for query in selected_queries:
            multi = query_vectors[query.query_id]
            tick = time.perf_counter()
            maxsim_k = min(32, len(pack.regions))
            query_result = hybrid_query(
                pack,
                query.query_text,
                _mean(multi),
                multi,
                top_n=len(pack.regions),
                maxsim_k=maxsim_k,
                limit=maxsim_k,
                maxsim_scorer=maxsim_numpy,
            )
            query_ms.append((time.perf_counter() - tick) * 1000)
            rescored = {hit.region_id: hit for hit in query_result.hits}
            complete_order = [hit.region_id for hit in query_result.hits] + [
                region_id
                for region_id in query_result.prefiltered_region_ids
                if region_id not in rescored
            ]
            rankings.append(
                {
                    "query_id": query.query_id,
                    "candidates": [
                        {"case_id": region_id, "score": float(len(complete_order) - rank)}
                        for rank, region_id in enumerate(complete_order)
                    ],
                }
            )
    finally:
        stop.set()
        sampler.join(timeout=2)
        peak_rss = max(peak_rss, process.memory_info().rss)
    raw = {
        "schema_version": "dsvire.full-corpus-query-ranking.v1",
        "query_registry_sha256": queries.content_sha256,
        "visual_registry_sha256": visual.content_sha256,
        "split": "development",
        "system": {"id": SYSTEM_ID, "sha256": system_sha},
        "candidate_case_ids": sorted(region["id"] for region in regions),
        "rankings": rankings,
    }
    artifact = load_full_corpus_ranking_artifact(raw, queries, visual)
    metrics_result = evaluate_full_corpus_rankings(queries, artifact)
    deterministic: dict[str, Any] = {
        "schema_version": "dsvire.full-corpus-colsmol-result.v1",
        "source": {
            "visual_registry_sha256": visual.content_sha256,
            "query_registry_sha256": queries.content_sha256,
            "model_manifest_sha256": manifest.content_sha256,
            "source_manifest": sorted(source_manifest, key=lambda item: str(item["document_id"])),
        },
        "system": raw["system"],
        "pack_sha256": pack.pack_sha256,
        "ranking_sha256": full_corpus_order_sha256(artifact),
        "scope": {
            "split": "development",
            "documents": len(documents),
            "queries": len(selected_queries),
            "candidate_cases": len(regions),
            "ranked_pairs": len(selected_queries) * len(regions),
        },
        "metrics": metrics_result["metrics"],
        "by_query_type": metrics_result["by_query_type"],
        "limitations": metrics_result["limitations"]
        + [
            "development-only corpus; publication remains disabled",
            "encoder receives only raw query strings and crop pixels",
        ],
    }
    deterministic["result_sha256"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    runtime = {
        "device": device,
        "total_seconds": round(time.perf_counter() - started, 6),
        "image_encode_mean_ms": round(statistics.fmean(encode_image_ms), 3),
        "image_encode_p95_ms": round(
            sorted(encode_image_ms)[round((len(encode_image_ms) - 1) * 0.95)], 3
        ),
        "query_encode_mean_ms": round(statistics.fmean(encode_query_ms), 3),
        "hot_query_mean_ms": round(statistics.fmean(query_ms), 3),
        "hot_query_p95_ms": round(sorted(query_ms)[round((len(query_ms) - 1) * 0.95)], 3),
        "peak_rss_bytes": int(peak_rss),
        "pack_bytes": len(json.dumps(pack_raw, separators=(",", ":")).encode()),
        "environment": {
            "os": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
    }
    private_query_vectors = build_query_vector_artifact(
        query_registry_sha256=queries.content_sha256,
        visual_registry_sha256=visual.content_sha256,
        model_id=encoder.model_id,
        model_sha256=encoder.model_sha256,
        dimension=encoder.dimension,
        queries=[
            {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "vectors": [list(row) for row in query_vectors[query.query_id]],
            }
            for query in sorted(selected_queries, key=lambda item: item.query_id)
        ],
    )
    return {**deterministic, "runtime": runtime}, raw, pack_raw, private_query_vectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "evaluation/models/colsmol-256m.v1.json"
    )
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, action="append", default=[])
    parser.add_argument("--download-cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--ranking-out", type=Path)
    parser.add_argument("--pack-out", type=Path)
    parser.add_argument(
        "--private-query-vectors-out",
        type=Path,
        help="private model-derived query vectors; never publish as a CI artifact",
    )
    args = parser.parse_args()
    if not args.cache_root and args.download_cache is None:
        parser.error("set at least one --cache-root or --download-cache")
    try:
        evidence, ranking, pack, private_query_vectors = run(
            args.registry,
            args.queries,
            args.manifest,
            args.model_root,
            args.cache_root,
            device=args.device,
            download_cache=args.download_cache,
            offline=args.offline,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    for path, value in (
        (args.json_out, evidence),
        (args.ranking_out, ranking),
        (args.pack_out, pack),
        (args.private_query_vectors_out, private_query_vectors),
    ):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

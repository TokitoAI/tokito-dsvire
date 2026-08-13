"""Run unscoped OpenCLIP query-to-crop retrieval over a complete registered split."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import threading
import time
from pathlib import Path
from typing import Any, TypedDict

import psutil
import pymupdf

from dsvire.corpus_coverage import load_query_registry
from dsvire.eval_sources import resolve_registered_sources
from dsvire.openclip_query_baseline import SYSTEM_ID, OpenClipQueryBaseline
from dsvire.query_ranking import (
    evaluate_full_corpus_rankings,
    full_corpus_order_sha256,
    load_full_corpus_ranking_artifact,
)
from dsvire.visual_adapters import OPENCLIP_MODEL_SHA256, render_registered_crop
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]


class RankedCandidate(TypedDict):
    case_id: str
    score: float


def run(
    registry_path: Path,
    query_path: Path,
    cache_roots: list[Path],
    model_path: Path,
    *,
    download_cache: Path | None = None,
    offline: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    visual = load_visual_registry_data(json.loads(registry_path.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(query_path.read_text(encoding="utf-8")), visual)
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

    sampler = threading.Thread(target=sample, name="openclip-rss", daemon=True)
    sampler.start()
    started = time.perf_counter()
    pngs: list[bytes] = []
    candidate_ids: list[str] = []
    source_manifest: list[dict[str, Any]] = []
    render_ms: list[float] = []
    try:
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
                    tick = time.perf_counter()
                    pngs.append(render_registered_crop(pdf, case))
                    render_ms.append((time.perf_counter() - tick) * 1000)
                    candidate_ids.append(f"{document.document_id}/{case.case_id}")
        baseline = OpenClipQueryBaseline(model_path)
        inference_started = time.perf_counter()
        matrix = baseline.rank([item.query_text for item in selected_queries], pngs)
        inference_seconds = time.perf_counter() - inference_started
    finally:
        stop.set()
        sampler.join(timeout=2)
        peak_rss = max(peak_rss, process.memory_info().rss)
    rankings = []
    for query, scores in zip(selected_queries, matrix, strict=True):
        candidates: list[RankedCandidate] = [
            {"case_id": case_id, "score": score}
            for case_id, score in zip(candidate_ids, scores, strict=True)
        ]
        candidates.sort(key=lambda item: (-item["score"], item["case_id"]))
        rankings.append({"query_id": query.query_id, "candidates": candidates})
    raw = {
        "schema_version": "dsvire.full-corpus-query-ranking.v1",
        "query_registry_sha256": queries.content_sha256,
        "visual_registry_sha256": visual.content_sha256,
        "split": "development",
        "system": {"id": SYSTEM_ID, "sha256": baseline.implementation_sha256},
        "candidate_case_ids": sorted(candidate_ids),
        "rankings": rankings,
    }
    artifact = load_full_corpus_ranking_artifact(raw, queries, visual)
    result = evaluate_full_corpus_rankings(queries, artifact)
    deterministic: dict[str, Any] = {
        "schema_version": "dsvire.full-corpus-openclip-baseline-result.v1",
        "source": {
            "visual_registry_sha256": visual.content_sha256,
            "query_registry_sha256": queries.content_sha256,
            "model_sha256": OPENCLIP_MODEL_SHA256,
            "source_manifest": sorted(source_manifest, key=lambda item: str(item["document_id"])),
        },
        "system": raw["system"],
        "ranking_sha256": full_corpus_order_sha256(artifact),
        "scope": {
            "split": "development",
            "documents": len(documents),
            "queries": len(selected_queries),
            "candidate_cases": len(candidate_ids),
            "ranked_pairs": len(selected_queries) * len(candidate_ids),
        },
        "metrics": result["metrics"],
        "by_query_type": result["by_query_type"],
        "limitations": result["limitations"]
        + ["scorer uses only raw query text and crop pixels; it is not identity assisted"],
    }
    deterministic["result_sha256"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **deterministic,
        "runtime": {
            "score_artifact_sha256": artifact.content_sha256,
            "total_seconds": round(time.perf_counter() - started, 6),
            "inference_seconds": round(inference_seconds, 6),
            "candidate_render_mean_ms": round(statistics.fmean(render_ms), 3),
            "candidate_render_p95_ms": round(
                sorted(render_ms)[round((len(render_ms) - 1) * 0.95)], 3
            ),
            "peak_rss_bytes": int(peak_rss),
            "external_cost_usd": 0.0,
            "environment": {
                "os": platform.system(),
                "os_release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "pymupdf": pymupdf.__version__,
                "logical_cpus": os.cpu_count(),
            },
        },
    }, raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument("--cache-root", type=Path, action="append", default=[])
    parser.add_argument("--download-cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--ranking-out", type=Path)
    args = parser.parse_args()
    if not args.cache_root and args.download_cache is None:
        parser.error("set at least one --cache-root or --download-cache")
    try:
        evidence, ranking = run(
            args.registry,
            args.queries,
            args.cache_root,
            args.model,
            download_cache=args.download_cache,
            offline=args.offline,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    if args.ranking_out:
        args.ranking_out.parent.mkdir(parents=True, exist_ok=True)
        args.ranking_out.write_text(
            json.dumps(ranking, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

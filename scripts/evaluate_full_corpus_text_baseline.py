"""Run the query-conditioned text baseline across a complete registered split."""

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

from dsvire.corpus_coverage import load_query_registry
from dsvire.eval_sources import resolve_registered_sources
from dsvire.pdf_backend import BACKEND_ID, PdfDocument
from dsvire.query_ranking import (
    evaluate_full_corpus_rankings,
    load_full_corpus_ranking_artifact,
)
from dsvire.text_query_baseline import (
    SYSTEM_ID,
    CandidateText,
    extract_candidate_text,
    implementation_sha256,
    score_query_candidate,
)
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]


class RankedCandidate(TypedDict):
    case_id: str
    score: float


class SourceManifestEntry(TypedDict):
    document_id: str
    content_sha256: str
    bytes: int


def run(
    registry_path: Path,
    query_path: Path,
    cache_roots: list[Path],
    split: str,
    *,
    download_cache: Path | None = None,
    offline: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    visual = load_visual_registry_data(json.loads(registry_path.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(query_path.read_text(encoding="utf-8")), visual)
    documents = tuple(document for document in visual.documents if document.split == split)
    selected_queries = tuple(query for query in queries.queries if query.split == split)
    source_paths = resolve_registered_sources(cache_roots, documents, download_cache, offline)
    process = psutil.Process()
    peak_rss = process.memory_info().rss
    stop_sampling = threading.Event()

    def sample_rss() -> None:
        nonlocal peak_rss
        while not stop_sampling.wait(0.01):
            peak_rss = max(peak_rss, process.memory_info().rss)

    sampler = threading.Thread(target=sample_rss, name="query-baseline-rss", daemon=True)
    started = time.perf_counter()
    sampler.start()
    candidates: list[CandidateText] = []
    extraction_latencies: list[float] = []
    source_manifest: list[SourceManifestEntry] = []
    rankings: list[dict[str, Any]] = []
    ranking_seconds = 0.0
    try:
        for document in documents:
            source = source_paths[document.content_sha256]
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != document.content_sha256:
                raise ValueError(f"source changed while reading: {document.document_id}")
            source_manifest.append(
                {
                    "document_id": document.document_id,
                    "content_sha256": document.content_sha256,
                    "bytes": len(payload),
                }
            )
            with PdfDocument(payload) as pdf:
                for case in document.cases:
                    case_started = time.perf_counter()
                    text = extract_candidate_text(pdf, document, case)
                    extraction_latencies.append((time.perf_counter() - case_started) * 1000)
                    candidates.append(
                        CandidateText(
                            f"{document.document_id}/{case.case_id}", document, case, text
                        )
                    )
        ranking_started = time.perf_counter()
        for query in selected_queries:
            scored: list[RankedCandidate] = [
                {"case_id": candidate.case_id, "score": score_query_candidate(query, candidate)}
                for candidate in candidates
            ]
            scored.sort(key=lambda item: (-item["score"], item["case_id"]))
            rankings.append({"query_id": query.query_id, "candidates": scored})
        ranking_seconds = time.perf_counter() - ranking_started
    finally:
        stop_sampling.set()
        sampler.join(timeout=2)
        peak_rss = max(peak_rss, process.memory_info().rss)
    raw = {
        "schema_version": "dsvire.full-corpus-query-ranking.v1",
        "query_registry_sha256": queries.content_sha256,
        "visual_registry_sha256": visual.content_sha256,
        "split": split,
        "system": {"id": SYSTEM_ID, "sha256": implementation_sha256()},
        "candidate_case_ids": sorted(candidate.case_id for candidate in candidates),
        "rankings": rankings,
    }
    artifact = load_full_corpus_ranking_artifact(raw, queries, visual)
    result = evaluate_full_corpus_rankings(queries, artifact)
    total_seconds = time.perf_counter() - started
    sorted_source_manifest = sorted(source_manifest, key=lambda entry: entry["document_id"])
    deterministic: dict[str, Any] = {
        "schema_version": "dsvire.full-corpus-text-baseline-result.v1",
        "source": {
            "visual_registry_sha256": visual.content_sha256,
            "query_registry_sha256": queries.content_sha256,
            "source_manifest": sorted_source_manifest,
        },
        "system": {"id": SYSTEM_ID, "sha256": implementation_sha256()},
        "ranking_sha256": artifact.content_sha256,
        "scope": {
            "split": split,
            "documents": len(documents),
            "queries": len(selected_queries),
            "candidate_cases": len(candidates),
            "ranked_pairs": len(selected_queries) * len(candidates),
        },
        "metrics": result["metrics"],
        "by_query_type": result["by_query_type"],
        "limitations": result["limitations"],
    }
    deterministic["result_sha256"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = {
        **deterministic,
        "runtime": {
            "total_seconds": round(total_seconds, 6),
            "ranking_seconds": round(ranking_seconds, 6),
            "queries_per_second": round(len(selected_queries) / ranking_seconds, 6),
            "candidate_extraction_mean_ms": round(statistics.fmean(extraction_latencies), 3),
            "candidate_extraction_p95_ms": round(
                sorted(extraction_latencies)[round((len(extraction_latencies) - 1) * 0.95)], 3
            ),
            "peak_rss_bytes": int(peak_rss),
            "external_cost_usd": 0.0,
            "environment": {
                "os": platform.system(),
                "os_release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "pdf_backend": BACKEND_ID,
                "logical_cpus": os.cpu_count(),
            },
        },
    }
    return evidence, raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument("--cache-root", type=Path, action="append", default=[])
    parser.add_argument("--download-cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--split", choices=["development"], default="development")
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
            args.split,
            download_cache=args.download_cache,
            offline=args.offline,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    if args.ranking_out is not None:
        args.ranking_out.parent.mkdir(parents=True, exist_ok=True)
        args.ranking_out.write_text(
            json.dumps(ranking, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

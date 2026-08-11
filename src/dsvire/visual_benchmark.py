"""Run candidate adapters against a strict visual annotation registry."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import statistics
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from .visual_adapters import VisualAdapter, score_document
from .visual_registry import VisualDocument, VisualRegistry, bind_prediction_scores

RESULT_VERSION = "dsvire.visual-adapter-benchmark.v1"


class _PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.01) -> None:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("install tokito-dsvire[visual] to measure peak RSS") from exc
        self._process = psutil.Process()
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._peak = self._process.memory_info().rss
        self._thread = threading.Thread(target=self._sample, name="dsvire-rss-sampler", daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(self._interval):
            self._peak = max(self._peak, self._process.memory_info().rss)

    def __enter__(self) -> _PeakRssSampler:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._peak = max(self._peak, self._process.memory_info().rss)

    @property
    def peak_bytes(self) -> int:
        return self._peak


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def benchmark_registry(
    registry: VisualRegistry,
    fetch: Callable[[VisualDocument], bytes],
    adapter: VisualAdapter,
) -> dict[str, Any]:
    started = time.perf_counter()
    score_map: dict[str, float] = {}
    documents: list[dict[str, Any]] = []
    latencies: list[float] = []
    with _PeakRssSampler() as memory:
        for document in registry.documents:
            payload = fetch(document)
            document_started = time.perf_counter()
            scores = score_document(adapter, payload, document)
            elapsed_ms = (time.perf_counter() - document_started) * 1000
            latencies.append(elapsed_ms)
            score_map.update(scores)
            documents.append(
                {
                    "id": document.document_id,
                    "document_group": document.document_group,
                    "split": document.split,
                    "review_status": document.review.status,
                    "elapsed_ms": round(elapsed_ms, 3),
                    "scores": [
                        {
                            "case_id": f"{document.document_id}/{case.case_id}",
                            "label": case.label,
                            "score": scores[f"{document.document_id}/{case.case_id}"],
                        }
                        for case in document.cases
                    ],
                }
            )
    predictions = bind_prediction_scores(registry, score_map)
    deterministic = {
        "registry_sha256": registry.content_sha256,
        "adapter": dataclasses.asdict(adapter.metadata),
        "scores": {prediction.case_id: prediction.score for prediction in predictions},
    }
    score_sha256 = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    labels = Counter(prediction.label for prediction in predictions)
    reviewed_calibration = sum(
        document.review.status == "reviewed" and document.split == "calibration"
        for document in registry.documents
    )
    reviewed_evaluation = sum(
        document.review.status == "reviewed" and document.split == "evaluation"
        for document in registry.documents
    )
    elapsed_seconds = time.perf_counter() - started
    return {
        "schema_version": RESULT_VERSION,
        "registry_sha256": registry.content_sha256,
        "score_sha256": score_sha256,
        "adapter": dataclasses.asdict(adapter.metadata),
        "eligible_for_policy_fitting": reviewed_calibration > 0,
        "summary": {
            "documents": len(registry.documents),
            "cases": len(predictions),
            "labels": dict(sorted(labels.items())),
            "reviewed_calibration_documents": reviewed_calibration,
            "reviewed_evaluation_documents": reviewed_evaluation,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "documents_per_second": round(len(registry.documents) / elapsed_seconds, 6),
            "document_latency_mean_ms": round(statistics.fmean(latencies), 3),
            "document_latency_p50_ms": round(_percentile(latencies, 0.5), 3),
            "document_latency_p95_ms": round(_percentile(latencies, 0.95), 3),
            "peak_rss_bytes": memory.peak_bytes,
            "external_cost_usd": 0.0,
        },
        "documents": documents,
    }

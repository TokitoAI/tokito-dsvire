from __future__ import annotations

import asyncio
import json

import pytest

from dsvire.load_evidence import (
    LoadEvidenceError,
    Sample,
    _percentile,
    _summary,
    run_service_load,
    write_report,
)


def test_nearest_rank_percentiles_and_summary_are_stable() -> None:
    samples = [
        Sample("warm", str(index), 200, value, 10) for index, value in enumerate([1, 2, 3, 4])
    ]
    assert _percentile([1, 2, 3, 4], 0.50) == 2
    assert _percentile([1, 2, 3, 4], 0.95) == 4
    assert _summary(samples, 2.0) == {
        "requests": 4,
        "statuses": {"200": 4},
        "latency_ms": {"min": 1, "p50": 2, "p95": 4, "p99": 4, "max": 4},
        "elapsed_seconds": 2.0,
        "throughput_requests_per_second": 2.0,
        "response_bytes": 40,
    }


def test_report_write_is_atomic_and_sorted(tmp_path) -> None:
    path = tmp_path / "evidence.json"
    write_report({"z": 1, "a": 2}, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2, "z": 1}
    assert not path.with_suffix(".json.tmp").exists()


def test_request_bounds_fail_before_starting_service() -> None:
    with pytest.raises(LoadEvidenceError, match="cold_requests"):
        asyncio.run(run_service_load(cold_requests=0))

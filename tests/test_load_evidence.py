from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
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


def test_committed_schema_accepts_report_shape() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "scripts/schema/service_load_evidence_v1.schema.json").read_text())
    sample = Sample("cold", "cold-000", 200, 1.0, 10)
    phase = _summary([sample], 1.0)
    report = {
        "schema_version": "dsvire.service-load-evidence.v1",
        "ok": True,
        "implementation": {
            "source_commit": "abcdef0",
            "dsvire_version": "0.3.1",
            "index_version": "v",
            "python": "3.12",
            "platform": "linux",
            "cpu_count": 2,
        },
        "workload": {
            "version": "dsvire.generated-http-load@1.0.0",
            "sha256": "a" * 64,
            "source": "deterministic generated PDF; no vendor bytes",
            "cold_requests": 1,
            "warm_requests": 1,
            "overload_requests": 2,
        },
        "service_config": {},
        "phases": {"cold": phase, "warm": phase, "overload": phase},
        "totals": {
            "requests": 4,
            "successful": 3,
            "overload_rejections": 1,
            "unexpected": 0,
            "peak_process_tree_rss_bytes": 1,
            "published_packs": 3,
            "published_bytes": 1,
            "scratch_entries_after_shutdown": 0,
            "partial_entries_after_shutdown": 0,
        },
        "slo_mapping": {
            "technical_bible_hot_pack_query_p95_ms": 800,
            "verdict": "not_applicable",
            "reason": "This indexing boundary is not the future hot-pack MaxSim query path.",
        },
        "samples": [sample.__dict__, sample.__dict__, sample.__dict__],
    }
    jsonschema.Draft202012Validator(schema).validate(report)

"""Reproducible load evidence for the authenticated production HTTP boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psutil

from . import __version__
from .pipeline import INDEX_VERSION
from .robustness import _born_digital

SCHEMA_VERSION = "dsvire.service-load-evidence.v1"
WORKLOAD_VERSION = "dsvire.generated-http-load@1.0.0"
UNKNOWN_COMMIT = "unknown"
TOKEN = "load-evidence-service-token-at-least-32-bytes"
IDENTITY = {
    "manufacturer": "Acme",
    "mpn": "A-1",
    "package": "SOIC-8",
}


class LoadEvidenceError(RuntimeError):
    """The service load run failed an integrity or lifecycle invariant."""


@dataclass(frozen=True)
class Sample:
    phase: str
    request_id: str
    status: int
    elapsed_ms: float
    response_bytes: int


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def _summary(samples: Sequence[Sample], elapsed_seconds: float) -> dict[str, Any]:
    latencies = [sample.elapsed_ms for sample in samples]
    statuses: dict[str, int] = {}
    for sample in samples:
        key = str(sample.status)
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "requests": len(samples),
        "statuses": dict(sorted(statuses.items())),
        "latency_ms": {
            "min": round(min(latencies), 3) if latencies else 0.0,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "elapsed_seconds": round(elapsed_seconds, 3),
        "throughput_requests_per_second": round(len(samples) / elapsed_seconds, 3)
        if elapsed_seconds > 0
        else 0.0,
        "response_bytes": sum(sample.response_bytes for sample in samples),
    }


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(port: int, payload: bytes, request_id: str, phase: str) -> Sample:
    query = urlencode(IDENTITY)
    request = Request(
        f"http://127.0.0.1:{port}/v1/evidence/symbol?{query}",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/pdf",
            "X-DSViRe-Load-Request": request_id,
        },
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            status = response.status
    except HTTPError as exc:
        body = exc.read()
        status = exc.code
    return Sample(
        phase=phase,
        request_id=request_id,
        status=status,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        response_bytes=len(body),
    )


def _tree_rss(root_pid: int) -> int:
    try:
        process = psutil.Process(root_pid)
        members = [process, *process.children(recursive=True)]
        return sum(member.memory_info().rss for member in members if member.is_running())
    except (psutil.Error, OSError):
        return 0


async def _sample_rss(process: subprocess.Popen[bytes], peaks: list[int]) -> None:
    while process.poll() is None:
        peaks.append(_tree_rss(process.pid))
        await asyncio.sleep(0.01)


async def _wait_ready(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise LoadEvidenceError(
                f"service exited before readiness: {(stderr or stdout)[-1000:].decode(errors='replace')}"
            )
        try:
            with urlopen(f"http://127.0.0.1:{port}/v1/ready", timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            await asyncio.sleep(0.05)
    raise LoadEvidenceError("service did not become ready within 15 seconds")


async def _phase(
    port: int, phase: str, payloads: Sequence[bytes], *, concurrent: bool
) -> tuple[list[Sample], float]:
    started = time.perf_counter()
    if concurrent:
        samples = await asyncio.gather(
            *(
                asyncio.to_thread(_request, port, payload, f"{phase}-{index:03d}", phase)
                for index, payload in enumerate(payloads)
            )
        )
    else:
        samples = []
        for index, payload in enumerate(payloads):
            samples.append(
                await asyncio.to_thread(_request, port, payload, f"{phase}-{index:03d}", phase)
            )
    return samples, time.perf_counter() - started


def _workload(cold_requests: int, warm_requests: int, overload_requests: int) -> dict[str, Any]:
    cold = [_born_digital(revision=f"LOAD-COLD-{index:03d}") for index in range(cold_requests)]
    warm_payload = _born_digital(revision="LOAD-WARM")
    warm = [warm_payload] * warm_requests
    overload = [
        _born_digital(revision=f"LOAD-OVERLOAD-{index:03d}") for index in range(overload_requests)
    ]
    digest = hashlib.sha256()
    for phase, payloads in (("cold", cold), ("warm", warm), ("overload", overload)):
        digest.update(phase.encode())
        for payload in payloads:
            digest.update(hashlib.sha256(payload).digest())
    return {"cold": cold, "warm": warm, "overload": overload, "sha256": digest.hexdigest()}


async def run_service_load(
    *,
    cold_requests: int = 3,
    warm_requests: int = 6,
    overload_requests: int = 6,
    source_commit: str = UNKNOWN_COMMIT,
) -> dict[str, Any]:
    """Run cold, warm-cache, and overload phases through a real Uvicorn process."""
    for name, value in (
        ("cold_requests", cold_requests),
        ("warm_requests", warm_requests),
        ("overload_requests", overload_requests),
    ):
        if value < 1 or value > 64:
            raise LoadEvidenceError(f"{name} must be in 1..=64")
    workload = _workload(cold_requests, warm_requests, overload_requests)
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="dsvire-load-") as directory:
        root = Path(directory)
        data_dir = root / "data"
        environment = os.environ.copy()
        environment.update(
            {
                "DSVIRE_DATA_DIR": str(data_dir),
                "DSVIRE_SERVICE_TOKEN": TOKEN,
                "DSVIRE_ENVIRONMENT": "test",
                "DSVIRE_MAX_CONCURRENT_JOBS": "1",
                "DSVIRE_ADMISSION_TIMEOUT_SECONDS": "0.1",
                "DSVIRE_JOB_TIMEOUT_SECONDS": "20",
                "DSVIRE_WORKER_CPU_SECONDS": "15",
                "DSVIRE_WORKER_MEMORY_BYTES": str(1024 * 1024 * 1024),
                "DSVIRE_WORKER_FILE_BYTES": str(128 * 1024 * 1024),
            }
        )
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "dsvire.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ]
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        peaks: list[int] = []
        sampler = asyncio.create_task(_sample_rss(process, peaks))
        all_samples: list[Sample] = []
        phase_reports: dict[str, Any] = {}
        try:
            await _wait_ready(port, process)
            for phase, concurrent in (("cold", False), ("warm", False), ("overload", True)):
                samples, elapsed = await _phase(port, phase, workload[phase], concurrent=concurrent)
                all_samples.extend(samples)
                phase_reports[phase] = _summary(samples, elapsed)
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
            except TimeoutError:
                process.kill()
                await asyncio.to_thread(process.wait)
            await sampler

        successful = sum(sample.status == 200 for sample in all_samples)
        overload_503 = sum(
            sample.phase == "overload" and sample.status == 503 for sample in all_samples
        )
        unexpected = [sample for sample in all_samples if sample.status not in {200, 503}]
        jobs_dir = data_dir / "jobs"
        scratch_entries = list(jobs_dir.iterdir()) if jobs_dir.exists() else []
        packs_dir = data_dir / "packs"
        evidence_files = list(packs_dir.rglob("evidence.json")) if packs_dir.exists() else []
        partial_files = (
            [
                path
                for path in packs_dir.rglob("*")
                if path.name.endswith((".tmp", ".corrupt")) or ".staging" in path.name
            ]
            if packs_dir.exists()
            else []
        )
        if unexpected:
            raise LoadEvidenceError(f"unexpected HTTP statuses: {[s.status for s in unexpected]}")
        if phase_reports["cold"]["statuses"] != {"200": cold_requests}:
            raise LoadEvidenceError("cold phase did not complete successfully")
        if phase_reports["warm"]["statuses"] != {"200": warm_requests}:
            raise LoadEvidenceError("warm phase did not complete successfully")
        if overload_503 < 1 or phase_reports["overload"]["statuses"].get("200", 0) < 1:
            raise LoadEvidenceError(
                "overload phase did not prove both progress and bounded rejection"
            )
        if scratch_entries or partial_files:
            raise LoadEvidenceError("worker scratch or partial publication residue remained")

        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "implementation": {
                "source_commit": source_commit,
                "dsvire_version": __version__,
                "index_version": INDEX_VERSION,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
            },
            "workload": {
                "version": WORKLOAD_VERSION,
                "sha256": workload["sha256"],
                "source": "deterministic generated PDF; no vendor bytes",
                "cold_requests": cold_requests,
                "warm_requests": warm_requests,
                "overload_requests": overload_requests,
            },
            "service_config": {
                "workers": 1,
                "max_concurrent_jobs": 1,
                "admission_timeout_seconds": 0.1,
                "job_timeout_seconds": 20,
                "worker_cpu_seconds": 15,
                "worker_memory_bytes": 1024 * 1024 * 1024,
                "worker_file_bytes": 128 * 1024 * 1024,
            },
            "phases": phase_reports,
            "totals": {
                "requests": len(all_samples),
                "successful": successful,
                "overload_rejections": overload_503,
                "unexpected": len(unexpected),
                "peak_process_tree_rss_bytes": max(peaks, default=0),
                "published_packs": len(evidence_files),
                "published_bytes": sum(
                    path.stat().st_size for path in packs_dir.rglob("*") if path.is_file()
                )
                if packs_dir.exists()
                else 0,
                "scratch_entries_after_shutdown": len(scratch_entries),
                "partial_entries_after_shutdown": len(partial_files),
            },
            "slo_mapping": {
                "technical_bible_hot_pack_query_p95_ms": 800,
                "verdict": "not_applicable",
                "reason": (
                    "This service is the synchronous PDF-to-evidence baseline, not the future "
                    "hot-pack MaxSim query path named by the v1 SLO. Its latency is recorded "
                    "without claiming SLO compliance."
                ),
            },
            "samples": [sample.__dict__ for sample in all_samples],
        }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)

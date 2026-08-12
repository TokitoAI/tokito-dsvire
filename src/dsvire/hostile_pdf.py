"""Deterministic malformed-PDF campaign executed through the production worker boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import psutil

from .pipeline import DatasheetIdentity, RetrievalError
from .robustness import _born_digital
from .worker import WorkerError, WorkerLimits, WorkerTimeout, run_pdf_job

SCHEMA = "dsvire.hostile-pdf-evidence.v1"
CAMPAIGN_SEED = 0xD5_71_2E
CASE_COUNT = 48
MAX_CASE_SECONDS = 5.0
MAX_PEAK_RSS_BYTES = 512 * 1024 * 1024
MAX_ERROR_BYTES = 512
Outcome = Literal["accepted", "rejected", "worker_error", "timeout"]


class HostilePdfError(RuntimeError):
    """A campaign invariant or resource ceiling failed closed."""


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    mutation: str
    source_sha256: str
    source_bytes: int
    outcome: Outcome
    elapsed_ms: int
    peak_rss_bytes: int
    published_packs: int


def generated_cases() -> tuple[tuple[str, str, bytes], ...]:
    base = _born_digital()
    randomizer = random.Random(CAMPAIGN_SEED)
    cases: list[tuple[str, str, bytes]] = []
    mutations = ("bit_flip", "zero_run", "truncate", "duplicate_slice", "token_replace", "append")
    for index in range(CASE_COUNT):
        mutation = mutations[index % len(mutations)]
        payload = _mutate(base, mutation, randomizer) + f"\n% dsvire-hostile-{index:03d}\n".encode()
        cases.append((f"hostile-{index:03d}", mutation, payload))
    return tuple(cases)


def _mutate(base: bytes, mutation: str, randomizer: random.Random) -> bytes:
    data = bytearray(base)
    if mutation == "bit_flip":
        for _ in range(randomizer.randint(1, 16)):
            offset = randomizer.randrange(len(data))
            data[offset] ^= 1 << randomizer.randrange(8)
    elif mutation == "zero_run":
        start = randomizer.randrange(len(data))
        length = min(randomizer.randint(1, 256), len(data) - start)
        data[start : start + length] = bytes(length)
    elif mutation == "truncate":
        del data[randomizer.randrange(8, len(data)) :]
    elif mutation == "duplicate_slice":
        start = randomizer.randrange(len(data))
        chunk = bytes(data[start : start + randomizer.randint(1, 256)])
        data[randomizer.randrange(len(data)) : 0] = chunk
    elif mutation == "token_replace":
        tokens = (b"xref", b"stream", b"endobj", b"/Font", b"/Image")
        token = tokens[randomizer.randrange(len(tokens))]
        position = data.find(token)
        if position >= 0:
            data[position : position + len(token)] = b"X" * len(token)
        else:
            data[randomizer.randrange(len(data))] = ord("X")
    elif mutation == "append":
        data.extend(bytes(randomizer.randrange(256) for _ in range(randomizer.randint(1, 512))))
    else:  # pragma: no cover - internal closed mutation set
        raise AssertionError(mutation)
    return bytes(data)


async def _run_case(case_id: str, mutation: str, payload: bytes, root: Path) -> CaseResult:
    data_dir = root / case_id
    limits = WorkerLimits(
        cpu_seconds=3, memory_bytes=MAX_PEAK_RSS_BYTES, file_bytes=64 * 1024 * 1024
    )
    started = time.perf_counter()
    task = asyncio.create_task(
        run_pdf_job(
            payload,
            DatasheetIdentity("Acme", "A-1", "SOIC-8"),
            data_dir,
            timeout_seconds=MAX_CASE_SECONDS,
            limits=limits,
        )
    )
    peak_rss = 0
    outcome: Outcome = "accepted"
    detail = ""
    while not task.done():
        peak_rss = max(peak_rss, _descendant_rss())
        await asyncio.sleep(0.01)
    try:
        await task
    except RetrievalError as exc:
        outcome, detail = "rejected", str(exc)
    except WorkerTimeout as exc:
        outcome, detail = "timeout", str(exc)
    except WorkerError as exc:
        outcome, detail = "worker_error", str(exc)
    elapsed = time.perf_counter() - started
    peak_rss = max(peak_rss, _descendant_rss())
    if elapsed > MAX_CASE_SECONDS + 2.5:
        raise HostilePdfError(f"{case_id}: wall-clock cleanup exceeded its bound")
    if peak_rss > MAX_PEAK_RSS_BYTES:
        raise HostilePdfError(f"{case_id}: observed RSS exceeded its kernel limit")
    if len(detail.encode("utf-8")) > MAX_ERROR_BYTES:
        raise HostilePdfError(f"{case_id}: diagnostic exceeded {MAX_ERROR_BYTES} bytes")
    jobs = data_dir / "jobs"
    if jobs.exists() and any(jobs.iterdir()):
        raise HostilePdfError(f"{case_id}: worker scratch data was not removed")
    packs = data_dir / "packs"
    evidence = list(packs.rglob("evidence.json")) if packs.exists() else []
    temporary = (
        [
            path
            for path in packs.rglob("*")
            if path.name.endswith((".tmp", ".corrupt")) or ".staging" in path.name
        ]
        if packs.exists()
        else []
    )
    if temporary:
        raise HostilePdfError(f"{case_id}: partial/corrupt publication residue remained")
    if outcome == "accepted" and len(evidence) != 1:
        raise HostilePdfError(f"{case_id}: accepted mutation did not publish exactly one pack")
    if outcome != "accepted" and evidence:
        raise HostilePdfError(f"{case_id}: failed mutation published evidence")
    return CaseResult(
        case_id,
        mutation,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        outcome,
        round(elapsed * 1000),
        peak_rss,
        len(evidence),
    )


def _descendant_rss() -> int:
    try:
        return sum(child.memory_info().rss for child in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        return 0


async def run_campaign() -> dict[str, Any]:
    cases = generated_cases()
    if cases != generated_cases():
        raise HostilePdfError("mutation campaign is not deterministic")
    with tempfile.TemporaryDirectory(prefix="dsvire-hostile-") as directory:
        results = [await _run_case(*case, Path(directory)) for case in cases]
    outcomes = {
        name: sum(result.outcome == name for result in results)
        for name in ("accepted", "rejected", "worker_error", "timeout")
    }
    return {
        "schema_version": SCHEMA,
        "ok": True,
        "seed": CAMPAIGN_SEED,
        "case_count": len(results),
        "campaign_sha256": hashlib.sha256(b"".join(case[2] for case in cases)).hexdigest(),
        "limits": {
            "case_timeout_seconds": MAX_CASE_SECONDS,
            "cpu_seconds": 3,
            "memory_bytes": MAX_PEAK_RSS_BYTES,
            "file_bytes": 64 * 1024 * 1024,
        },
        "outcomes": outcomes,
        "elapsed_ms": {
            "max": max(result.elapsed_ms for result in results),
            "p95": sorted(result.elapsed_ms for result in results)[len(results) * 95 // 100 - 1],
        },
        "peak_rss_bytes": max(result.peak_rss_bytes for result in results),
        "cases": [asdict(result) for result in results],
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)

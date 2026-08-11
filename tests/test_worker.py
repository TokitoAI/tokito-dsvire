from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from dsvire.pipeline import DatasheetIdentity
from dsvire.worker import WorkerLimits, WorkerTimeout, run_pdf_job


def _success_target(upload, identity, output, result, limits) -> None:
    assert Path(upload).read_bytes() == b"%PDF-test"
    Path(result).write_text(
        json.dumps({"status": "ok", "bundle": {"schema_version": "test"}}),
        encoding="utf-8",
    )


def _sleep_target(upload, identity, output, result, limits) -> None:
    time.sleep(10)


def _limits() -> WorkerLimits:
    return WorkerLimits(cpu_seconds=1, memory_bytes=512 * 1024 * 1024, file_bytes=64 * 1024 * 1024)


def test_worker_result_and_scratch_cleanup(tmp_path: Path) -> None:
    result = asyncio.run(
        run_pdf_job(
            b"%PDF-test",
            DatasheetIdentity("Acme", "A1", "SOIC-8"),
            tmp_path,
            timeout_seconds=2,
            limits=_limits(),
            worker_target=_success_target,
        )
    )
    assert result["schema_version"] == "test"
    assert list((tmp_path / "jobs").iterdir()) == []


def test_timed_out_worker_is_killed_and_scratch_is_removed(tmp_path: Path) -> None:
    with pytest.raises(WorkerTimeout):
        asyncio.run(
            run_pdf_job(
                b"%PDF-test",
                DatasheetIdentity("Acme", "A1", "SOIC-8"),
                tmp_path,
                timeout_seconds=0.2,
                limits=_limits(),
                worker_target=_sleep_target,
            )
        )
    assert list((tmp_path / "jobs").iterdir()) == []


def test_cancelled_worker_is_killed_and_scratch_is_removed(tmp_path: Path) -> None:
    async def scenario() -> None:
        task = asyncio.create_task(
            run_pdf_job(
                b"%PDF-test",
                DatasheetIdentity("Acme", "A1", "SOIC-8"),
                tmp_path,
                timeout_seconds=5,
                limits=_limits(),
                worker_target=_sleep_target,
            )
        )
        jobs = tmp_path / "jobs"
        for _ in range(100):
            if jobs.exists() and any(jobs.iterdir()):
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert list((tmp_path / "jobs").iterdir()) == []

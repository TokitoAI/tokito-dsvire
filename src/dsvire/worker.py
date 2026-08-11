"""Killable subprocess boundary for parsing untrusted PDF documents."""

from __future__ import annotations

import asyncio
import importlib
import json
import multiprocessing
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from .pipeline import DatasheetIdentity, RetrievalError, retrieve_symbol_evidence


class WorkerError(RuntimeError):
    """The isolated worker failed without a safe retrieval error."""


class WorkerTimeout(WorkerError):
    """The isolated worker exceeded its wall-clock deadline."""


@dataclass(frozen=True)
class WorkerLimits:
    cpu_seconds: int
    memory_bytes: int
    file_bytes: int


def _apply_resource_limits(limits: WorkerLimits) -> None:
    """Apply kernel-enforced limits on Unix; the process boundary still applies elsewhere."""
    try:
        resource: Any = importlib.import_module("resource")
    except ImportError:  # pragma: no cover - Windows has no resource module
        return

    def cap(kind: int, requested: int) -> None:
        _soft, hard = resource.getrlimit(kind)
        target = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        resource.setrlimit(kind, (target, target))

    cap(resource.RLIMIT_CPU, limits.cpu_seconds)
    cap(resource.RLIMIT_AS, limits.memory_bytes)
    cap(resource.RLIMIT_FSIZE, limits.file_bytes)
    cap(resource.RLIMIT_NOFILE, 64)
    if hasattr(resource, "RLIMIT_CORE"):
        cap(resource.RLIMIT_CORE, 0)


def _write_result(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def _worker_main(
    upload_path: Path,
    identity: DatasheetIdentity,
    output_root: Path,
    result_path: Path,
    limits: WorkerLimits,
) -> None:
    _apply_resource_limits(limits)
    try:
        bundle = retrieve_symbol_evidence(upload_path.read_bytes(), identity, output_root)
        _write_result(result_path, {"status": "ok", "bundle": bundle})
    except RetrievalError as exc:
        _write_result(result_path, {"status": "retrieval_error", "detail": str(exc)})
    except BaseException as exc:  # child must return a bounded, non-payload diagnostic
        _write_result(
            result_path,
            {"status": "worker_error", "detail": f"{type(exc).__name__}: worker failed"},
        )


class _Process(Protocol):
    @property
    def exitcode(self) -> int | None: ...

    def is_alive(self) -> bool: ...
    def join(self, timeout: float | None = None) -> None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


def _terminate(process: _Process) -> None:
    if not process.is_alive():
        process.join(timeout=0.1)
        return
    process.terminate()
    process.join(timeout=2.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=2.0)


async def run_pdf_job(
    pdf_bytes: bytes,
    identity: DatasheetIdentity,
    data_dir: Path,
    *,
    timeout_seconds: float,
    limits: WorkerLimits,
    worker_target: Callable[..., None] = _worker_main,
) -> dict[str, Any]:
    """Run one job and remove its private scratch directory on every exit path."""
    jobs_dir = data_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    job_dir = Path(tempfile.mkdtemp(prefix="job-", dir=jobs_dir))
    try:
        with suppress(OSError):  # best effort on Windows ACL-backed paths
            job_dir.chmod(0o700)
        upload_path = job_dir / "upload.pdf"
        result_path = job_dir / "result.json"
        upload_path.write_bytes(pdf_bytes)
        with suppress(OSError):
            upload_path.chmod(0o600)

        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=worker_target,
            args=(upload_path, identity, data_dir / "packs", result_path, limits),
            name="dsvire-pdf-worker",
        )
        process.start()
        try:
            await asyncio.wait_for(asyncio.to_thread(process.join), timeout_seconds)
        except TimeoutError as exc:
            _terminate(process)
            raise WorkerTimeout(f"PDF worker exceeded {timeout_seconds:g} seconds") from exc
        except asyncio.CancelledError:
            _terminate(process)
            raise

        if process.exitcode != 0:
            raise WorkerError(f"PDF worker exited with code {process.exitcode}")
        if not result_path.is_file():
            raise WorkerError("PDF worker exited without a result")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkerError("PDF worker returned an invalid result") from exc
        if result.get("status") == "retrieval_error":
            raise RetrievalError(str(result.get("detail", "retrieval failed")))
        if result.get("status") != "ok" or not isinstance(result.get("bundle"), dict):
            raise WorkerError(str(result.get("detail", "PDF worker failed")))
        return cast(dict[str, Any], result["bundle"])
    finally:
        process_obj = locals().get("process")
        if process_obj is not None:
            _terminate(process_obj)
        shutil.rmtree(job_dir, ignore_errors=True)

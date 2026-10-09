"""Private app scan-context generation from operator-reviewed dataset bindings."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from .board_dataset import (
    MAX_METADATA_BYTES,
    bounded_read,
    dataset_file,
    metadata,
    plan_board_symbols,
)
from .config import ServiceConfig
from .pipeline import IdentityHint, RetrievalError
from .worker import WorkerError, WorkerLimits, WorkerTimeout, run_symbol_job

RESULT_SCHEMA = "dsvire.board-symbols.v1"
MAX_PARTS = 8
MAX_RESULT_BYTES = 4 * 1024 * 1024
# Reserve room for all bounded identities, statuses and the board envelope.
DRAFT_BUDGET_BYTES = MAX_RESULT_BYTES - 64 * 1024


class BoardCapacityFull(RuntimeError):
    """No admission slot was available before any dataset read began."""


def _release_after_read(task: asyncio.Task[Any], admission: asyncio.Semaphore) -> None:
    def release(completed: asyncio.Task[Any]) -> None:
        admission.release()
        if not completed.cancelled():
            completed.exception()  # Consume errors from reads abandoned by cancelled requests.

    if task.done():
        release(task)
    else:
        # to_thread cannot stop a running file read; retain its slot until it actually ends.
        task.add_done_callback(release)


async def load_board_binding_admitted(
    data_dir: Path,
    tenant: UUID,
    context_revision: str,
    admission: asyncio.Semaphore,
    admission_timeout: float,
) -> dict[str, Any]:
    try:
        await asyncio.wait_for(admission.acquire(), admission_timeout)
    except TimeoutError as exc:
        raise BoardCapacityFull from exc
    read = asyncio.create_task(
        asyncio.to_thread(load_board_binding, data_dir, tenant, context_revision)
    )
    try:
        return await asyncio.shield(read)
    finally:
        _release_after_read(read, admission)


def _bounded_pdf(path: Path, maximum: int) -> bytes:
    return bounded_read(path, maximum)


def load_board_binding(data_dir: Path, tenant: UUID, context_revision: str) -> dict[str, Any]:
    key = hashlib.sha256(context_revision.encode()).hexdigest()
    path = data_dir / "board-bindings" / str(tenant) / f"{key}.json"
    if not path.is_file():
        raise RetrievalError("reviewed board context unavailable")
    binding, _ = metadata(path.parent, path.name)
    if (
        not isinstance(binding, dict)
        or binding.get("schema_version") != "dsvire.board-binding.v1"
        or binding.get("context_revision") != context_revision
        or binding.get("review_status") != "approved"
        or not isinstance(binding.get("board_revision"), str)
        or not binding["board_revision"].strip()
        or len(binding["board_revision"]) > 256
        or not isinstance(binding.get("reviewed_by"), str)
        or not binding["reviewed_by"].strip()
        or len(binding["reviewed_by"]) > 256
    ):
        raise RetrievalError("board binding is not independently reviewed")
    if not isinstance(binding.get("board_family"), str) or len(binding["board_family"]) > 128:
        raise RetrievalError("invalid board family")
    dataset = data_dir / "board-dataset"
    plan = plan_board_symbols(dataset, binding.get("board_family", ""))
    sources = binding.get("dataset_sources")
    if sources != plan["sources"]:
        raise RetrievalError("dataset source revision mismatch")
    # Registration review is separate from source relation: a community clone
    # or a different-revision document never becomes exact by board detection.
    proof = binding.get("specimen_match")
    if not isinstance(proof, dict) or proof.get("status") != "reviewed_exact":
        raise RetrievalError("exact physical specimen mapping is required")
    proof_path = dataset_file(dataset, proof.get("path", ""))
    if hashlib.sha256(bounded_read(proof_path, MAX_METADATA_BYTES)).hexdigest() != proof.get(
        "sha256"
    ):
        raise RetrievalError("specimen match proof digest mismatch")
    parts = binding.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        raise RetrievalError("reviewed board binding must contain 1..8 parts")
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, dict):
            raise RetrievalError("invalid reviewed component binding")
        reference = part.get("reference")
        if (
            not isinstance(reference, str)
            or not reference.strip()
            or len(reference) > 64
            or reference in seen
        ):
            raise RetrievalError("component references must be nonempty and unique")
        seen.add(reference)
        for name, maximum in (("manufacturer", 160), ("mpn", 120), ("package", 120)):
            if (
                not isinstance(part.get(name), str)
                or not part[name].strip()
                or len(part[name]) > maximum
            ):
                raise RetrievalError("exact manufacturer, MPN and package are required")
        if part.get("catalog_status") not in {"missing", "resolved"}:
            raise RetrievalError("reviewed exact catalog resolution is required")
        if part["catalog_status"] == "resolved":
            if (
                not isinstance(part.get("catalog_revision"), str)
                or not part["catalog_revision"].strip()
                or len(part["catalog_revision"]) > 256
            ):
                raise RetrievalError("existing catalog symbol must carry a revision")
            continue
        pins = part.get("expected_pin_numbers")
        if not isinstance(pins, list) or not 4 <= len(pins) <= 2048:
            raise RetrievalError("missing symbol requires a reviewed complete pin set")
        if any(not isinstance(pin, str) or not pin.strip() for pin in pins) or len(
            set(pins)
        ) != len(pins):
            raise RetrievalError("reviewed pin numbers must be unique nonempty strings")
        if not isinstance(part.get("datasheet"), dict):
            raise RetrievalError("missing symbol requires a hash-bound local datasheet")
    return binding


async def generate_board_symbols(
    binding: dict[str, Any], config: ServiceConfig, admission: asyncio.Semaphore
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    remaining = DRAFT_BUDGET_BYTES
    dataset = config.data_dir / "board-dataset"
    for part in binding["parts"]:
        entry = {
            "reference": part["reference"],
            "identity": {name: part[name] for name in ("manufacturer", "mpn", "package")},
        }
        if part["catalog_status"] == "resolved":
            results.append(
                {**entry, "status": "existing", "catalog_revision": part["catalog_revision"]}
            )
            continue
        try:
            document = part["datasheet"]
            path = dataset_file(dataset, document.get("path", ""))
            try:
                await asyncio.wait_for(admission.acquire(), config.admission_timeout_seconds)
            except TimeoutError:
                results.append({**entry, "status": "unavailable", "code": "capacity_full"})
                continue
            read = asyncio.create_task(asyncio.to_thread(_bounded_pdf, path, config.max_pdf_bytes))
            try:
                pdf = await asyncio.shield(read)
                if hashlib.sha256(pdf).hexdigest() != document.get("sha256"):
                    raise RetrievalError("datasheet digest mismatch")
                result = await run_symbol_job(
                    pdf,
                    IdentityHint(
                        part["manufacturer"],
                        part["mpn"],
                        part["package"],
                        document.get("source_url"),
                    ),
                    config.data_dir,
                    timeout_seconds=config.job_timeout_seconds,
                    limits=WorkerLimits(
                        config.worker_cpu_seconds,
                        config.worker_memory_bytes,
                        config.worker_file_bytes,
                    ),
                )
            finally:
                _release_after_read(read, admission)
            if result["identity"] != entry["identity"]:
                raise RetrievalError("generated symbol identity mismatch")
            actual_pins = [pin["number"] for pin in result["pins"]]
            if set(actual_pins) != set(part["expected_pin_numbers"]) or len(actual_pins) != len(
                part["expected_pin_numbers"]
            ):
                raise RetrievalError(
                    "generated symbol does not match the complete reviewed pin set"
                )
            public = {key: value for key, value in result.items() if key != "evidence"}
            draft = {
                **entry,
                "status": "draft",
                "symbol": public,
                "document_sha256": document["sha256"],
            }
            size = len(json.dumps(draft, ensure_ascii=False).encode("utf-8"))
            if size > remaining:
                results.append({**entry, "status": "unavailable", "code": "result_size_limit"})
            else:
                remaining -= size
                results.append(draft)
        except (RetrievalError, OSError, ValueError, TypeError):
            results.append(
                {**entry, "status": "abstained", "code": "insufficient_verified_evidence"}
            )
        except WorkerTimeout:
            results.append({**entry, "status": "unavailable", "code": "worker_timeout"})
        except WorkerError:
            results.append({**entry, "status": "unavailable", "code": "worker_failed"})
    return {
        "schema_version": RESULT_SCHEMA,
        "context_revision": binding["context_revision"],
        "board_family": binding["board_family"],
        "board_revision": binding["board_revision"],
        "publication_allowed": False,
        "components": results,
    }

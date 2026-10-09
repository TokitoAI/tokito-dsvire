"""Private app scan-context generation from operator-reviewed dataset bindings."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

from .board_dataset import dataset_file, metadata, plan_board_symbols
from .config import ServiceConfig
from .pipeline import IdentityHint, RetrievalError
from .worker import WorkerError, WorkerLimits, WorkerTimeout, run_symbol_job

RESULT_SCHEMA = "dsvire.board-symbols.v1"
MAX_PARTS = 8


def _bounded_pdf(path: Path, maximum: int) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(maximum + 1)
    if len(payload) > maximum:
        raise RetrievalError("datasheet exceeds PDF byte limit")
    return payload


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
        or not isinstance(binding.get("reviewed_by"), str)
        or not binding["reviewed_by"].strip()
    ):
        raise RetrievalError("board binding is not independently reviewed")
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
    if proof_path.stat().st_size > 16 * 1024 * 1024:
        raise RetrievalError("specimen match proof exceeds its byte limit")
    if hashlib.sha256(proof_path.read_bytes()).hexdigest() != proof.get("sha256"):
        raise RetrievalError("specimen match proof digest mismatch")
    parts = binding.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        raise RetrievalError("reviewed board binding must contain 1..8 parts")
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, dict):
            raise RetrievalError("invalid reviewed component binding")
        reference = part.get("reference")
        if not isinstance(reference, str) or not reference.strip() or reference in seen:
            raise RetrievalError("component references must be nonempty and unique")
        seen.add(reference)
        for name in ("manufacturer", "mpn", "package"):
            if not isinstance(part.get(name), str) or not part[name].strip():
                raise RetrievalError("exact manufacturer, MPN and package are required")
        if part.get("catalog_status") not in {"missing", "resolved"}:
            raise RetrievalError("reviewed exact catalog resolution is required")
        if part["catalog_status"] == "resolved":
            if not isinstance(part.get("catalog_revision"), str) or not part["catalog_revision"]:
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
            try:
                pdf = await asyncio.to_thread(_bounded_pdf, path, config.max_pdf_bytes)
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
                admission.release()
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
            results.append(
                {
                    **entry,
                    "status": "draft",
                    "symbol": public,
                    "document_sha256": document["sha256"],
                }
            )
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

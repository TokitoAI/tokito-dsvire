"""Lease-based DS-ViRe worker; safe under duplicates, crashes, and reconnects."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path
from typing import Any

from .bundle import build_bundle
from .config import ServiceConfig
from .object_store import LocalObjectStore, ObjectStore, S3ObjectStore
from .pipeline import DatasheetIdentity, RetrievalError
from .platform_config import PlatformConfig
from .platform_db import Lease, PlatformDatabase
from .worker import WorkerError, WorkerLimits, WorkerTimeout, run_pdf_job

logger = logging.getLogger(__name__)


def make_object_store(config: PlatformConfig) -> ObjectStore:
    if config.local_object_dir is not None:
        return LocalObjectStore(config.local_object_dir)
    return S3ObjectStore(
        bucket=config.object_bucket,
        region=config.object_region,
        access_key=config.object_access_key,
        secret_key=config.object_secret_key,
        endpoint=config.object_endpoint,
    )


async def _artifacts(data_dir: Path, evidence: dict[str, Any]) -> dict[str, bytes]:
    files = {"evidence.json": (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()}
    regions = evidence.get("regions", [])
    for region in regions:
        uri = region.get("crop_uri", "")
        parts = uri.removeprefix("dsvire://pack/").split("/", 1)
        if len(parts) != 2 or parts[1].startswith("../"):
            raise WorkerError("worker returned an unsafe crop URI")
        crop = data_dir / "packs" / parts[0] / "crops" / parts[1]
        files[f"crops/{parts[1]}"] = await asyncio.to_thread(crop.read_bytes)
    return files


async def process_lease(
    database: PlatformDatabase,
    objects: ObjectStore,
    platform: PlatformConfig,
    service: ServiceConfig,
    lease: Lease,
    owner: str,
) -> None:
    if not await database.heartbeat(lease.job_id, owner, "downloading", platform.lease_seconds):
        await database.finish(lease.job_id, owner)
        return
    try:
        payload = await objects.read_verified(lease.document)
        request = lease.request
        identity = DatasheetIdentity(
            str(request["manufacturer"]),
            str(request["mpn"]),
            str(request["package"]),
            str(request["source_url"]) if request.get("source_url") else None,
        )
        if not await database.heartbeat(lease.job_id, owner, "extracting", platform.lease_seconds):
            await database.finish(lease.job_id, owner)
            return
        evidence = await run_pdf_job(
            payload,
            identity,
            service.data_dir,
            timeout_seconds=service.job_timeout_seconds,
            limits=WorkerLimits(
                service.worker_cpu_seconds,
                service.worker_memory_bytes,
                service.worker_file_bytes,
            ),
        )
        files = await _artifacts(service.data_dir, evidence)
        bundle = build_bundle(
            files,
            {
                "job_id": str(lease.job_id),
                "document_sha256": lease.document.sha256,
                "pipeline_version": evidence.get("schema_version"),
            },
        )
        bundle_ref = await objects.put_immutable(
            str(lease.tenant_id), "bundle", bundle.payload, "zip", "application/zip"
        )
        evidence_ref = await objects.put_immutable(
            str(lease.tenant_id), "evidence", files["evidence.json"], "json", "application/json"
        )
        await database.finish(
            lease.job_id,
            owner,
            result={
                "schema_version": "dsvire.job-result.v1",
                "bundle": bundle_ref.__dict__,
                "evidence": evidence_ref.__dict__,
            },
        )
    except RetrievalError:
        await database.finish(lease.job_id, owner, error_code="invalid_or_unsupported_pdf")
    except WorkerTimeout:
        await database.finish(
            lease.job_id, owner, error_code="worker_timeout", retryable=True
        )
    except (WorkerError, OSError):
        logger.exception("DS-ViRe lease failed", extra={"job_id": str(lease.job_id)})
        await database.finish(lease.job_id, owner, error_code="worker_failed", retryable=True)


async def run_forever() -> None:
    platform = PlatformConfig.from_env()
    service = ServiceConfig.from_env()
    service.prepare()
    database = await PlatformDatabase.connect(platform.database_url)
    objects = make_object_store(platform)
    owner = f"{socket.gethostname()}:{id(asyncio.current_task())}"
    try:
        await database.migrate()
        while True:
            lease = await database.lease_next(owner, platform.lease_seconds)
            if lease is None:
                await asyncio.sleep(1)
                continue
            await process_lease(database, objects, platform, service, lease, owner)
    finally:
        await database.close()


def main() -> int:
    asyncio.run(run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

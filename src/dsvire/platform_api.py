"""Tenant-scoped asynchronous upload, job, cancellation, and replay API."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from .object_store import ObjectStore
from .platform_db import JobConflict, JobNotFound, PlatformDatabase

platform_router = APIRouter(prefix="/v1/platform")
_IDEMPOTENCY = re.compile(r"^[\x21-\x7e]{8,200}$")


async def _principal(request: Request, authorization: str | None) -> UUID:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
        )
    database: PlatformDatabase | None = getattr(request.app.state, "platform_db", None)
    if database is None:
        raise HTTPException(status_code=503, detail="platform unavailable")
    tenant_id = await database.authenticate(authorization.removeprefix("Bearer "))
    if tenant_id is None:
        raise HTTPException(
            status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"}
        )
    return tenant_id


async def _pdf(request: Request, maximum: int) -> bytes:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="content-type must be application/pdf")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="PDF exceeds configured size limit")
        body.extend(chunk)
    if len(body) < 8 or not body.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="invalid PDF envelope")
    return bytes(body)


def _public_job(row: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], jsonable_encoder(row))


@platform_router.post("/jobs", status_code=202)
async def submit_job(
    request: Request,
    manufacturer: str = Query(min_length=1, max_length=160),
    mpn: str = Query(min_length=1, max_length=120),
    package: str = Query(min_length=1, max_length=120),
    source_url: str | None = Query(default=None, max_length=2048),
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    tenant_id = await _principal(request, authorization)
    if idempotency_key is None or not _IDEMPOTENCY.fullmatch(idempotency_key):
        raise HTTPException(status_code=400, detail="valid Idempotency-Key header required")
    service = request.app.state.config
    payload = await _pdf(request, service.max_pdf_bytes)
    objects: ObjectStore = request.app.state.object_store
    reference = await objects.put_immutable(
        str(tenant_id), "pdf", payload, "pdf", "application/pdf"
    )
    request_body = {
        "schema_version": "dsvire.job-request.v1",
        "manufacturer": manufacturer,
        "mpn": mpn,
        "package": package,
        "source_url": source_url,
        "document_sha256": reference.sha256,
    }
    database: PlatformDatabase = request.app.state.platform_db
    try:
        job_id, created = await database.submit(
            tenant_id=tenant_id,
            document=reference,
            idempotency_key=idempotency_key,
            request=request_body,
            max_attempts=request.app.state.platform_config.max_attempts,
        )
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        {"job_id": str(job_id), "created": created, "state": "queued"},
        status_code=202 if created else 200,
        headers={"Location": f"/v1/platform/jobs/{job_id}"},
    )


@platform_router.get("/jobs/{job_id}")
async def get_job(
    request: Request, job_id: UUID, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    tenant_id = await _principal(request, authorization)
    try:
        return _public_job(await request.app.state.platform_db.get_job(tenant_id, job_id))
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@platform_router.delete("/jobs/{job_id}", status_code=202)
async def cancel_job(
    request: Request, job_id: UUID, authorization: str | None = Header(default=None)
) -> dict[str, str]:
    tenant_id = await _principal(request, authorization)
    if not await request.app.state.platform_db.request_cancel(tenant_id, job_id):
        raise HTTPException(status_code=409, detail="job cannot be cancelled")
    return {"job_id": str(job_id), "status": "cancel_requested"}


def _sse(event: dict[str, Any]) -> bytes:
    payload = json.dumps(jsonable_encoder(event["payload"]), separators=(",", ":"))
    return f"id: {event['event_id']}\nevent: {event['kind']}\ndata: {payload}\n\n".encode()


@asynccontextmanager
async def _poll_ticks() -> AsyncIterator[AsyncIterator[None]]:
    async def ticks() -> AsyncIterator[None]:
        while True:
            await asyncio.sleep(1)
            yield None

    yield ticks()


@platform_router.get("/jobs/{job_id}/events")
async def job_events(
    request: Request,
    job_id: UUID,
    authorization: str | None = Header(default=None),
    last_event_id: int = Header(default=0, alias="Last-Event-ID", ge=0),
) -> StreamingResponse:
    tenant_id = await _principal(request, authorization)
    database: PlatformDatabase = request.app.state.platform_db
    try:
        await database.get_job(tenant_id, job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc

    async def stream() -> AsyncIterator[bytes]:
        cursor = last_event_id
        idle = 0
        redis_events = getattr(request.app.state, "redis_events", None)
        subscription = redis_events.subscribe(str(job_id)) if redis_events else _poll_ticks()
        async with subscription as ticks:
            # Query once before waiting so reconnects replay without fan-out history.
            pending_tick = True
            while not await request.is_disconnected():
                if not pending_tick:
                    await anext(ticks)
                pending_tick = False
                events = await database.events(tenant_id, job_id, cursor)
                if events:
                    idle = 0
                    for event in events:
                        cursor = event["event_id"]
                        yield _sse(event)
                    job = await database.get_job(tenant_id, job_id)
                    if job["state"] in {"succeeded", "failed", "cancelled"}:
                        return
                else:
                    idle += 1
                    if idle % 15 == 0:
                        yield b": keepalive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )

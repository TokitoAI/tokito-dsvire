"""Authenticated, bounded hosted DS-ViRe service boundary."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import __version__
from .config import ServiceConfig
from .pipeline import DatasheetIdentity, RetrievalError
from .query_worker import QueryRejected, run_query_job
from .trace import TraceContext
from .worker import WorkerError, WorkerLimits, WorkerTimeout, run_pdf_job

router = APIRouter()
logger = logging.getLogger(__name__)


def _authorize(authorization: str | None, config: ServiceConfig) -> None:
    if not config.service_token:
        # Config validation only permits this in an explicitly insecure local/test mode.
        return
    expected = f"Bearer {config.service_token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "tokito-dsvire", "version": __version__}


@router.get("/v1/ready")
async def ready(request: Request) -> dict[str, str]:
    # Startup validation and creation of the admission controller are the readiness gate.
    if not hasattr(request.app.state, "admission"):
        raise HTTPException(status_code=503, detail="not ready")
    database = getattr(request.app.state, "platform_db", None)
    qdrant = getattr(request.app.state, "qdrant", None)
    if database is not None and qdrant is not None:
        try:
            await database.ping()
            await qdrant.ping()
        except Exception as exc:
            logger.warning("platform dependency readiness failed", exc_info=exc)
            raise HTTPException(status_code=503, detail="platform dependencies not ready") from exc
    return {"status": "ready", "service": "tokito-dsvire", "version": __version__}


async def _read_bounded_body(request: Request, maximum: int, noun: str) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length") from exc
        if declared_bytes < 0:
            raise HTTPException(status_code=400, detail="invalid content-length")
        if declared_bytes > maximum:
            raise HTTPException(status_code=413, detail=f"{noun} exceeds configured size limit")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail=f"{noun} exceeds configured size limit")
        body.extend(chunk)
    return bytes(body)


@router.post("/v1/evidence/symbol")
async def symbol_evidence(
    request: Request,
    manufacturer: str = Query(min_length=1, max_length=160),
    mpn: str = Query(min_length=1, max_length=120),
    package: str = Query(min_length=1, max_length=120),
    source_url: str | None = Query(default=None, max_length=2_048),
    authorization: str | None = Header(default=None),
    traceparent: str | None = Header(default=None),
) -> JSONResponse:
    config: ServiceConfig = request.app.state.config
    _authorize(authorization, config)
    trace = TraceContext.parse(traceparent) or TraceContext.generate()
    logger.info("DS-ViRe retrieval admitted", extra={"trace_id": trace.trace_id})
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="content-type must be application/pdf")

    admission: asyncio.Semaphore = request.app.state.admission
    try:
        await asyncio.wait_for(admission.acquire(), timeout=config.admission_timeout_seconds)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="PDF processing capacity is currently full",
            headers={"Retry-After": "2"},
        ) from exc

    try:
        body = await _read_bounded_body(request, config.max_pdf_bytes, "PDF")
        try:
            bundle = await run_pdf_job(
                body,
                DatasheetIdentity(manufacturer, mpn, package, source_url),
                config.data_dir,
                timeout_seconds=config.job_timeout_seconds,
                limits=WorkerLimits(
                    cpu_seconds=config.worker_cpu_seconds,
                    memory_bytes=config.worker_memory_bytes,
                    file_bytes=config.worker_file_bytes,
                ),
            )
        except RetrievalError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except WorkerTimeout as exc:
            raise HTTPException(status_code=504, detail="PDF processing timed out") from exc
        except WorkerError as exc:
            raise HTTPException(status_code=502, detail="PDF processing worker failed") from exc
        return JSONResponse(bundle, headers={"traceparent": trace.child().header()})
    finally:
        admission.release()


@router.post("/v1/query")
async def query_regions(
    request: Request,
    authorization: str | None = Header(default=None),
    traceparent: str | None = Header(default=None),
) -> JSONResponse:
    config: ServiceConfig = request.app.state.config
    _authorize(authorization, config)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(status_code=415, detail="content-type must be application/json")
    admission: asyncio.Semaphore = request.app.state.query_admission
    try:
        await asyncio.wait_for(admission.acquire(), timeout=config.admission_timeout_seconds)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503, detail="query capacity is currently full", headers={"Retry-After": "1"}
        ) from exc
    trace = TraceContext.parse(traceparent) or TraceContext.generate()
    logger.info("DS-ViRe query admitted", extra={"trace_id": trace.trace_id})
    try:
        body = await _read_bounded_body(request, config.max_query_bytes, "query request")
        try:
            result = await run_query_job(
                body,
                config.data_dir,
                timeout_seconds=config.query_timeout_seconds,
                limits=WorkerLimits(
                    cpu_seconds=max(
                        1, min(config.worker_cpu_seconds, int(config.query_timeout_seconds) + 1)
                    ),
                    memory_bytes=config.worker_memory_bytes,
                    file_bytes=config.worker_file_bytes,
                ),
            )
        except QueryRejected as exc:
            raise HTTPException(status_code=422, detail="query or pack failed validation") from exc
        except WorkerTimeout as exc:
            raise HTTPException(status_code=504, detail="query timed out") from exc
        except WorkerError as exc:
            raise HTTPException(status_code=502, detail="query worker failed") from exc
        logger.info(
            "DS-ViRe query completed",
            extra={
                "trace_id": trace.trace_id,
                "considered": result.get("considered"),
                "maxsim_evaluated": result.get("maxsim_evaluated"),
                "hit_count": len(result.get("hits", [])),
            },
        )
        return JSONResponse(result, headers={"traceparent": trace.child().header()})
    finally:
        admission.release()


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active = ServiceConfig.from_env() if config is None else config
        active.prepare()
        application.state.config = active
        application.state.admission = asyncio.Semaphore(active.max_concurrent_jobs)
        application.state.query_admission = asyncio.Semaphore(active.max_concurrent_queries)
        platform_enabled = os.environ.get("DSVIRE_PLATFORM_ENABLED", "").casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        platform_db = None
        redis_events = None
        qdrant = None
        outbox_stop = asyncio.Event()
        outbox_task = None
        try:
            if platform_enabled:
                from .accelerators import QdrantIndex, RedisEvents, dispatch_outbox
                from .object_store import LocalObjectStore, S3ObjectStore
                from .platform_config import PlatformConfig
                from .platform_db import PlatformDatabase

                platform = PlatformConfig.from_env()
                platform_db = await PlatformDatabase.connect(platform.database_url)
                await platform_db.migrate()
                await platform_db.ping()
                application.state.platform_config = platform
                application.state.platform_db = platform_db
                application.state.object_store = (
                    LocalObjectStore(platform.local_object_dir)
                    if platform.local_object_dir is not None
                    else S3ObjectStore(
                        bucket=platform.object_bucket,
                        region=platform.object_region,
                        access_key=platform.object_access_key,
                        secret_key=platform.object_secret_key,
                        endpoint=platform.object_endpoint,
                    )
                )
                redis_events = RedisEvents(platform.redis_url)
                qdrant = QdrantIndex(platform.qdrant_url, platform.qdrant_api_key)
                await qdrant.ping()
                application.state.redis_events = redis_events
                application.state.qdrant = qdrant
                outbox_task = asyncio.create_task(
                    dispatch_outbox(platform_db, redis_events, outbox_stop),
                    name="dsvire-outbox",
                )
            yield
        finally:
            outbox_stop.set()
            if outbox_task is not None:
                await outbox_task
            if redis_events is not None:
                await redis_events.close()
            if qdrant is not None:
                await qdrant.close()
            if platform_db is not None:
                await platform_db.close()

    application = FastAPI(
        title="Tokito DS-ViRe",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.include_router(router)
    from .platform_api import platform_router

    application.include_router(platform_router)
    return application


app = create_app()

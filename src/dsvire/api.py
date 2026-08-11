"""Authenticated, bounded hosted DS-ViRe service boundary."""

from __future__ import annotations

import asyncio
import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import __version__
from .config import ServiceConfig
from .pipeline import DatasheetIdentity, RetrievalError
from .worker import WorkerError, WorkerLimits, WorkerTimeout, run_pdf_job

router = APIRouter()


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
def ready(request: Request) -> dict[str, str]:
    # Startup validation and creation of the admission controller are the readiness gate.
    if not hasattr(request.app.state, "admission"):
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready", "service": "tokito-dsvire", "version": __version__}


async def _read_bounded_pdf(request: Request, maximum: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length") from exc
        if declared_bytes < 0:
            raise HTTPException(status_code=400, detail="invalid content-length")
        if declared_bytes > maximum:
            raise HTTPException(status_code=413, detail="PDF exceeds configured size limit")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(status_code=413, detail="PDF exceeds configured size limit")
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
) -> JSONResponse:
    config: ServiceConfig = request.app.state.config
    _authorize(authorization, config)
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
        body = await _read_bounded_pdf(request, config.max_pdf_bytes)
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
        return JSONResponse(bundle)
    finally:
        admission.release()


def create_app(config: ServiceConfig | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active = ServiceConfig.from_env() if config is None else config
        active.validate()
        active.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            active.data_dir.chmod(0o700)
        probe = active.data_dir / f".write-probe-{os.getpid()}"
        try:
            with probe.open("xb") as handle:
                handle.write(b"ready")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            probe.unlink(missing_ok=True)
        application.state.config = active
        application.state.admission = asyncio.Semaphore(active.max_concurrent_jobs)
        yield

    application = FastAPI(
        title="Tokito DS-ViRe",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()

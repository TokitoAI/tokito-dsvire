"""Hosted DS-ViRe query service.

Tokito Cloud is the authenticated public boundary. This service is intended to
run on the private service network and requires a shared bearer when configured.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import __version__
from .pipeline import DatasheetIdentity, RetrievalError, retrieve_symbol_evidence

app = FastAPI(title="Tokito DS-ViRe", version=__version__, docs_url=None, redoc_url=None)
DATA_DIR = Path(os.environ.get("DSVIRE_DATA_DIR", "/data/dsvire"))
SERVICE_TOKEN = os.environ.get("DSVIRE_SERVICE_TOKEN", "").strip()
MAX_PDF_BYTES = 64 * 1024 * 1024


def _authorize(authorization: str | None) -> None:
    if not SERVICE_TOKEN:
        return
    expected = f"Bearer {SERVICE_TOKEN}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "tokito-dsvire", "version": __version__}


async def _read_bounded_pdf(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length") from exc
        if declared_bytes < 0:
            raise HTTPException(status_code=400, detail="invalid content-length")
        if declared_bytes > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="PDF exceeds 64 MiB")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="PDF exceeds 64 MiB")
        body.extend(chunk)
    return bytes(body)


@app.post("/v1/evidence/symbol")
async def symbol_evidence(
    request: Request,
    manufacturer: str = Query(min_length=1, max_length=160),
    mpn: str = Query(min_length=1, max_length=120),
    package: str = Query(min_length=1, max_length=120),
    source_url: str | None = Query(default=None, max_length=2_048),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    _authorize(authorization)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="content-type must be application/pdf")
    body = await _read_bounded_pdf(request)
    try:
        # PDF parsing and crop rendering are CPU-bound and must not block the
        # service event loop while other uploads and health checks are served.
        bundle = await run_in_threadpool(
            retrieve_symbol_evidence,
            body,
            DatasheetIdentity(manufacturer, mpn, package, source_url),
            DATA_DIR / "packs",
        )
    except RetrievalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(bundle)

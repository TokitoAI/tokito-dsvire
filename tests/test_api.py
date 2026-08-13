from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from dsvire import api
from dsvire.config import ConfigurationError, ServiceConfig
from dsvire.pipeline import RetrievalError
from dsvire.trace import TraceContext
from dsvire.worker import WorkerError, WorkerTimeout

TOKEN = "test-service-token-that-is-at-least-32-bytes"


def _url() -> str:
    return (
        "/v1/evidence/symbol?manufacturer=Texas%20Instruments&mpn=TPS5430DDAR&package=SO-PowerPAD-8"
    )


def _config(tmp_path: Path, **overrides) -> ServiceConfig:
    values = {
        "data_dir": tmp_path,
        "service_token": TOKEN,
        "environment": "test",
        "max_concurrent_jobs": 1,
        "admission_timeout_seconds": 0.1,
        "job_timeout_seconds": 2.0,
        "worker_cpu_seconds": 1,
    }
    values.update(overrides)
    return ServiceConfig(**values)


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"content-type": "application/pdf", "authorization": f"Bearer {token}"}


def test_health_and_readiness_are_safe_without_auth(tmp_path: Path) -> None:
    with TestClient(api.create_app(_config(tmp_path))) as client:
        health = client.get("/v1/health")
        ready = client.get("/v1/ready")
    assert health.status_code == 200
    assert health.json()["service"] == "tokito-dsvire"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_startup_refuses_missing_service_token(tmp_path: Path) -> None:
    config = _config(tmp_path, service_token="", environment="production")
    with (
        pytest.raises(ConfigurationError, match="SERVICE_TOKEN is required"),
        TestClient(api.create_app(config)),
    ):
        pass


def test_startup_refuses_unusable_data_path(tmp_path: Path) -> None:
    data_file = tmp_path / "not-a-directory"
    data_file.write_text("occupied", encoding="utf-8")
    with pytest.raises(FileExistsError), TestClient(api.create_app(_config(data_file))):
        pass


def test_symbol_evidence_requires_private_service_bearer(tmp_path: Path) -> None:
    with TestClient(api.create_app(_config(tmp_path))) as client:
        response = client.post(
            _url(), content=b"%PDF-fake", headers={"content-type": "application/pdf"}
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_symbol_evidence_stream_is_bounded(tmp_path: Path) -> None:
    with TestClient(api.create_app(_config(tmp_path, max_pdf_bytes=1024))) as client:
        response = client.post(_url(), content=b"x" * 1025, headers=_headers())
    assert response.status_code == 413


def test_symbol_evidence_runs_isolated_retrieval(monkeypatch, tmp_path: Path) -> None:
    async def fake_run(body, identity, data_dir, *, timeout_seconds, limits):
        assert body == b"%PDF-fake"
        assert identity.mpn == "TPS5430DDAR"
        assert data_dir == tmp_path
        assert timeout_seconds == 2.0
        return {"schema_version": "dsvire.symbol-evidence.v2", "regions": []}

    monkeypatch.setattr(api, "run_pdf_job", fake_run)
    with TestClient(api.create_app(_config(tmp_path))) as client:
        headers = _headers() | {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }
        response = client.post(_url(), content=b"%PDF-fake", headers=headers)
    assert response.status_code == 200
    returned = TraceContext.parse(response.headers["traceparent"])
    assert returned is not None
    assert returned.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert returned.parent_id != "00f067aa0ba902b7"
    assert response.json()["schema_version"] == "dsvire.symbol-evidence.v2"


def test_invalid_traceparent_is_replaced(monkeypatch, tmp_path: Path) -> None:
    async def fake_run(*args, **kwargs):
        return {"schema_version": "dsvire.symbol-evidence.v2", "regions": []}

    monkeypatch.setattr(api, "run_pdf_job", fake_run)
    with TestClient(api.create_app(_config(tmp_path))) as client:
        response = client.post(
            _url(), content=b"%PDF-fake", headers=_headers() | {"traceparent": "attacker-data"}
        )
    assert response.status_code == 200
    assert TraceContext.parse(response.headers["traceparent"]) is not None


@pytest.mark.parametrize(
    ("error", "status"),
    [(WorkerTimeout("slow"), 504), (WorkerError("crashed"), 502)],
)
def test_worker_failures_have_stable_public_errors(
    monkeypatch, tmp_path: Path, error, status
) -> None:
    async def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(api, "run_pdf_job", fail)
    with TestClient(api.create_app(_config(tmp_path))) as client:
        response = client.post(_url(), content=b"%PDF-fake", headers=_headers())
    assert response.status_code == status
    assert "crashed" not in response.text


def test_repaired_pdf_rejection_has_stable_unprocessable_response(
    monkeypatch, tmp_path: Path
) -> None:
    async def reject(*args, **kwargs):
        raise RetrievalError("PDF required parser repair and was rejected")

    monkeypatch.setattr(api, "run_pdf_job", reject)
    with TestClient(api.create_app(_config(tmp_path))) as client:
        response = client.post(_url(), content=b"%PDF-repaired", headers=_headers())

    assert response.status_code == 422
    assert response.json() == {"detail": "PDF required parser repair and was rejected"}


def test_capacity_is_bounded_before_upload_processing(monkeypatch, tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    async def blocking_run(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 2)
        return {"schema_version": "dsvire.symbol-evidence.v2", "regions": []}

    monkeypatch.setattr(api, "run_pdf_job", blocking_run)
    with (
        TestClient(api.create_app(_config(tmp_path, admission_timeout_seconds=0.1))) as client,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(client.post, _url(), content=b"%PDF-one", headers=_headers())
        assert entered.wait(1)
        second = client.post(_url(), content=b"%PDF-two", headers=_headers())
        release.set()
        assert first.result(timeout=2).status_code == 200
    assert second.status_code == 503
    assert second.headers["retry-after"] == "2"


def test_hybrid_query_requires_auth_and_returns_trace(monkeypatch, tmp_path: Path) -> None:
    async def fake_query(body, data_dir, *, timeout_seconds, limits):
        assert json.loads(body) == {"pack_sha256": "1" * 64}
        assert data_dir == tmp_path
        assert timeout_seconds == 10.0
        return {"schema_version": "dsvire.hybrid-query-result.v1", "hits": []}

    import json

    monkeypatch.setattr(api, "run_query_job", fake_query)
    with TestClient(api.create_app(_config(tmp_path))) as client:
        denied = client.post("/v1/query", json={"pack_sha256": "1" * 64})
        response = client.post(
            "/v1/query",
            json={"pack_sha256": "1" * 64},
            headers={"authorization": f"Bearer {TOKEN}"},
        )
    assert denied.status_code == 401
    assert response.status_code == 200
    assert TraceContext.parse(response.headers["traceparent"]) is not None


def test_hybrid_query_body_is_bounded(tmp_path: Path) -> None:
    with TestClient(api.create_app(_config(tmp_path, max_query_bytes=1024))) as client:
        response = client.post(
            "/v1/query",
            content=b"x" * 1025,
            headers={"content-type": "application/json", "authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 413

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dsvire.object_store import LocalObjectStore
from dsvire.platform_api import platform_router


class FakeDatabase:
    def __init__(self) -> None:
        self.tenant = uuid4()
        self.job = uuid4()
        self.submissions = []

    async def authenticate(self, token: str) -> UUID | None:
        return self.tenant if token == "dsv_live_valid" else None

    async def submit(self, **values):
        self.submissions.append(values)
        return self.job, True

    async def get_job(self, tenant_id: UUID, job_id: UUID):
        assert tenant_id == self.tenant and job_id == self.job
        return {
            "job_id": job_id,
            "state": "succeeded",
            "stage": "complete",
            "attempt": 1,
            "max_attempts": 5,
            "cancel_requested": False,
            "result": {},
            "error_code": None,
        }

    async def events(self, tenant_id: UUID, job_id: UUID, after: int):
        return [{"event_id": 7, "kind": "succeeded", "payload": {}}] if after < 7 else []

    async def request_cancel(self, tenant_id: UUID, job_id: UUID) -> bool:
        return tenant_id == self.tenant and job_id == self.job


def _client(tmp_path: Path) -> tuple[TestClient, FakeDatabase]:
    app = FastAPI()
    app.include_router(platform_router)
    database = FakeDatabase()
    app.state.platform_db = database
    app.state.object_store = LocalObjectStore(tmp_path)
    app.state.config = SimpleNamespace(max_pdf_bytes=1024)
    app.state.platform_config = SimpleNamespace(max_attempts=5)
    return TestClient(app), database


def _headers() -> dict[str, str]:
    return {
        "authorization": "Bearer dsv_live_valid",
        "content-type": "application/pdf",
        "idempotency-key": "request-0001",
    }


def test_submit_is_authenticated_bounded_and_idempotent(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    url = "/v1/platform/jobs?manufacturer=TI&mpn=TPS5430&package=SOIC-8"
    denied = client.post(url, content=b"%PDF-1.7 x", headers={"content-type": "application/pdf"})
    accepted = client.post(url, content=b"%PDF-1.7 x", headers=_headers())
    assert denied.status_code == 401
    assert accepted.status_code == 202
    assert accepted.json() == {
        "job_id": str(database.job),
        "created": True,
        "state": "queued",
    }
    assert database.submissions[0]["document"].key.startswith(
        f"tenants/{database.tenant}/pdf/"
    )


def test_job_and_replayable_sse_are_tenant_scoped(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    headers = {"authorization": "Bearer dsv_live_valid"}
    status = client.get(f"/v1/platform/jobs/{database.job}", headers=headers)
    events = client.get(
        f"/v1/platform/jobs/{database.job}/events",
        headers=headers | {"last-event-id": "0"},
    )
    assert status.status_code == 200
    assert status.json()["state"] == "succeeded"
    assert events.status_code == 200
    assert "id: 7\nevent: succeeded\ndata: {}" in events.text

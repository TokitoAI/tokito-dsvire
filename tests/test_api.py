from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from dsvire import api


def _url() -> str:
    return (
        "/v1/evidence/symbol?manufacturer=Texas%20Instruments"
        "&mpn=TPS5430DDAR&package=SO-PowerPAD-8"
    )


def test_health_is_safe_without_auth() -> None:
    response = TestClient(api.app).get("/v1/health")
    assert response.status_code == 200
    assert response.json()["service"] == "tokito-dsvire"


def test_symbol_evidence_requires_private_service_bearer(monkeypatch) -> None:
    monkeypatch.setattr(api, "SERVICE_TOKEN", "secret")
    response = TestClient(api.app).post(
        _url(), content=b"%PDF-fake", headers={"content-type": "application/pdf"}
    )
    assert response.status_code == 401


def test_symbol_evidence_stream_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(api, "SERVICE_TOKEN", "")
    monkeypatch.setattr(api, "MAX_PDF_BYTES", 4)
    response = TestClient(api.app).post(
        _url(), content=b"12345", headers={"content-type": "application/pdf"}
    )
    assert response.status_code == 413


def test_symbol_evidence_runs_retrieval(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(api, "SERVICE_TOKEN", "secret")
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)

    def fake_retrieve(body, identity, output_root):
        assert body == b"%PDF-fake"
        assert identity.mpn == "TPS5430DDAR"
        assert output_root == tmp_path / "packs"
        return {"schema_version": "dsvire.symbol-evidence.v1", "regions": []}

    monkeypatch.setattr(api, "retrieve_symbol_evidence", fake_retrieve)
    response = TestClient(api.app).post(
        _url(),
        content=b"%PDF-fake",
        headers={
            "content-type": "application/pdf",
            "authorization": "Bearer secret",
        },
    )
    assert response.status_code == 200
    assert response.json()["schema_version"] == "dsvire.symbol-evidence.v1"

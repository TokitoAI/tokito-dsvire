from __future__ import annotations

from pathlib import Path

import pytest

from dsvire import server
from dsvire.config import ConfigurationError


def test_server_preflight_fails_before_uvicorn_without_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DSVIRE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DSVIRE_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("DSVIRE_ALLOW_INSECURE_DEV", raising=False)
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    with pytest.raises(ConfigurationError, match="SERVICE_TOKEN is required"):
        server.main()
    assert not called


def test_server_preflight_probes_storage_then_starts_uvicorn(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DSVIRE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DSVIRE_SERVICE_TOKEN", "x" * 32)
    invocation = {}

    def fake_run(app, **kwargs):
        invocation.update(app=app, **kwargs)

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    server.main()
    assert invocation["app"] == "dsvire.api:app"
    assert invocation["workers"] == 2
    assert invocation["limit_concurrency"] == 32
    assert list(tmp_path.glob(".write-probe-*")) == []

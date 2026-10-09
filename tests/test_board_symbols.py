from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dsvire.board_dataset import bounded_read, plan_board_symbols
from dsvire.board_symbols import generate_board_symbols, load_board_binding
from dsvire.config import ServiceConfig
from dsvire.pdf_fixtures import text_pdf
from dsvire.pipeline import RetrievalError
from dsvire.platform_api import platform_router


def _app(tmp_path: Path, tenant: UUID, **limits: float) -> FastAPI:
    class Database:
        async def authenticate(self, token: str) -> UUID | None:
            return tenant if token == "tenant-test-key" else None

    app = FastAPI()
    app.include_router(platform_router)
    app.state.platform_db = Database()
    app.state.config = ServiceConfig(data_dir=tmp_path, service_token="x" * 32, **limits)
    app.state.admission = asyncio.Semaphore(1)
    return app


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _binding(tmp_path: Path) -> tuple[dict, UUID, Path]:
    dataset = tmp_path / "board-dataset"
    (dataset / "sources/n236").mkdir(parents=True)
    _json(
        dataset / "data/photo-model/source-bundles.json",
        {
            "nxp_frdm_mcxn236_board": {
                "path": "sources/n236",
                "relation": "revision_unconfirmed",
                "exact_component_mapping": False,
                "incompatible_bundle": "sources/n947",
            },
        },
    )
    _json(dataset / "data/photo-model/component-seed-annotations.json", {"images": []})
    _json(dataset / "data/photo-model/large-board-component-seeds.json", {"images": []})
    _json(
        dataset / "data/photo-model/nxp-component-seeds.json",
        {"annotations": [{"class_name": "integrated_circuit", "manufacturer_part_number": None}]},
    )
    proof = dataset / "sources/n236/specimen-review.json"
    _json(proof, {"review": "synthetic test specimen correspondence"})
    payload = text_pdf(
        [
            "Acme A-1 SOIC-8\nPin Configuration - top view\nVIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
            "Pin Functions\nPin Name Type Description\n1 VIN input\n2 BOOT passive\n3 PH output\n4 GND ground\n5 VSENSE input\n6 ENA input\n7 COMP passive\n8 PWRPAD ground",
        ]
    )
    pdf = dataset / "sources/n236/part.pdf"
    pdf.write_bytes(payload)
    binding = {
        "schema_version": "dsvire.board-binding.v1",
        "context_revision": "test-board@sha256:123",
        "review_status": "approved",
        "reviewed_by": "synthetic-test-reviewer",
        "board_revision": "C",
        "board_family": "nxp_frdm_mcxn236_board",
        "dataset_sources": plan_board_symbols(dataset, "nxp_frdm_mcxn236_board")["sources"],
        "specimen_match": {
            "status": "reviewed_exact",
            "path": "sources/n236/specimen-review.json",
            "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
        },
        "parts": [
            {
                "reference": "U1",
                "manufacturer": "Acme",
                "mpn": "A-1",
                "package": "SOIC-8",
                "catalog_status": "missing",
                "expected_pin_numbers": [str(x) for x in range(1, 9)],
                "datasheet": {
                    "path": "sources/n236/part.pdf",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
            }
        ],
    }
    tenant = uuid4()
    path = (
        tmp_path
        / "board-bindings"
        / str(tenant)
        / f"{hashlib.sha256(binding['context_revision'].encode()).hexdigest()}.json"
    )
    _json(path, binding)
    return binding, tenant, path


def test_visual_seed_is_never_an_exact_part_or_generation_permission(tmp_path: Path) -> None:
    _binding(tmp_path)
    plan = plan_board_symbols(tmp_path / "board-dataset", "nxp_frdm_mcxn236_board")
    assert plan["generation_ready_count"] == 0
    assert plan["exact_component_mapping"] is False
    assert plan["incompatible_bundle"] == "sources/n947"
    assert plan["components"][0]["mpn"] is None
    with pytest.raises(RetrievalError, match="unknown"):
        plan_board_symbols(tmp_path / "board-dataset", "nxp_frdm_mcxn947_board")


def test_private_bindings_reject_other_tenant_source_changes_and_incomplete_review(
    tmp_path: Path,
) -> None:
    binding, tenant, path = _binding(tmp_path)
    assert load_board_binding(tmp_path, tenant, binding["context_revision"]) == binding
    with pytest.raises(RetrievalError):
        load_board_binding(tmp_path, uuid4(), binding["context_revision"])
    binding["review_status"] = "pending"
    _json(path, binding)
    with pytest.raises(RetrievalError, match="reviewed"):
        load_board_binding(tmp_path, tenant, binding["context_revision"])
    binding["review_status"] = "approved"
    _json(path, binding)
    _json(tmp_path / "board-dataset/data/photo-model/nxp-component-seeds.json", {"annotations": []})
    with pytest.raises(RetrievalError, match="revision mismatch"):
        load_board_binding(tmp_path, tenant, binding["context_revision"])


def test_real_pdf_worker_generates_draft_but_never_publishes(tmp_path: Path) -> None:
    binding, tenant, _ = _binding(tmp_path)
    loaded = load_board_binding(tmp_path, tenant, binding["context_revision"])
    config = ServiceConfig(data_dir=tmp_path, service_token="x" * 32)
    result = asyncio.run(generate_board_symbols(loaded, config, asyncio.Semaphore(1)))
    assert result["publication_allowed"] is False
    part = result["components"][0]
    assert part["status"] == "draft"
    assert len(part["symbol"]["pins"]) == 8
    assert part["symbol"]["identity"]["mpn"] == "A-1"
    assert part["symbol"]["citations"]


def test_pin_coverage_and_pdf_hash_mismatch_abstain(tmp_path: Path) -> None:
    binding, _, _ = _binding(tmp_path)
    config = ServiceConfig(data_dir=tmp_path, service_token="x" * 32)
    binding["parts"][0]["expected_pin_numbers"].append("9")
    result = asyncio.run(generate_board_symbols(binding, config, asyncio.Semaphore(1)))
    assert result["components"][0]["status"] == "abstained"
    binding["parts"][0]["datasheet"]["sha256"] = "0" * 64
    result = asyncio.run(generate_board_symbols(binding, config, asyncio.Semaphore(1)))
    assert result["components"][0]["status"] == "abstained"


def test_existing_catalog_revision_skips_generation(tmp_path: Path) -> None:
    binding, tenant, path = _binding(tmp_path)
    binding["parts"][0].update(
        catalog_status="resolved", catalog_revision="exact-reviewed-revision"
    )
    _json(path, binding)
    loaded = load_board_binding(tmp_path, tenant, binding["context_revision"])
    (tmp_path / "board-dataset/sources/n236/part.pdf").unlink()
    result = asyncio.run(
        generate_board_symbols(
            loaded, ServiceConfig(data_dir=tmp_path, service_token="x" * 32), asyncio.Semaphore(1)
        )
    )
    assert result["components"][0]["status"] == "existing"


def test_api_requires_tenant_auth_and_exact_context(tmp_path: Path) -> None:
    binding, tenant, path = _binding(tmp_path)
    binding["parts"][0].update(catalog_status="resolved", catalog_revision="r1")
    _json(path, binding)

    app = _app(tmp_path, tenant)
    client = TestClient(app)
    url = "/v1/platform/board-symbols"
    params = {"context_revision": binding["context_revision"]}
    assert client.post(url, params=params).status_code == 401
    headers = {"authorization": "Bearer tenant-test-key"}
    assert (
        client.post(url, params={"context_revision": "wrong"}, headers=headers).status_code == 409
    )
    accepted = client.post(url, params=params, headers=headers)
    assert accepted.status_code == 200
    assert accepted.json()["components"][0]["status"] == "existing"
    assert accepted.json()["publication_allowed"] is False


def test_overloaded_api_does_not_read_binding_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_read(*args: object) -> dict:
        pytest.fail("An unadmitted request read dataset files")

    monkeypatch.setattr("dsvire.board_symbols.load_board_binding", unexpected_read)
    app = _app(tmp_path, uuid4(), admission_timeout_seconds=0.01)
    app.state.admission = asyncio.Semaphore(0)
    response = TestClient(app).post(
        "/v1/platform/board-symbols",
        params={"context_revision": "board@1"},
        headers={"authorization": "Bearer tenant-test-key"},
    )
    assert response.status_code == 503


def test_deadline_covers_binding_read_and_retains_its_slot_until_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    finish = threading.Event()

    def blocked_read(*args: object) -> dict:
        started.set()
        assert finish.wait(2)
        raise RetrievalError("Read failed after caller timeout")

    monkeypatch.setattr("dsvire.board_symbols.load_board_binding", blocked_read)

    async def scenario() -> None:
        app = _app(tmp_path, uuid4(), admission_timeout_seconds=0.01, job_timeout_seconds=0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                response = await client.post(
                    "/v1/platform/board-symbols",
                    params={"context_revision": "board@1"},
                    headers={"authorization": "Bearer tenant-test-key"},
                )
                assert started.is_set()
                assert response.status_code == 504
                assert app.state.admission.locked()
                overloaded = await client.post(
                    "/v1/platform/board-symbols",
                    params={"context_revision": "board@1"},
                    headers={"authorization": "Bearer tenant-test-key"},
                )
                assert overloaded.status_code == 503
            finally:
                finish.set()
                async with asyncio.timeout(2):
                    while app.state.admission.locked():
                        await asyncio.sleep(0.01)

    asyncio.run(scenario())


def test_cancelled_pdf_read_retains_its_slot_until_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, _, _ = _binding(tmp_path)
    started = threading.Event()
    finish = threading.Event()

    def blocked_pdf(path: Path, maximum: int) -> bytes:
        started.set()
        assert finish.wait(2)
        return b"not-a-PDF"

    monkeypatch.setattr("dsvire.board_symbols._bounded_pdf", blocked_pdf)

    async def scenario() -> None:
        admission = asyncio.Semaphore(1)
        task = asyncio.create_task(
            generate_board_symbols(
                binding, ServiceConfig(data_dir=tmp_path, service_token="x" * 32), admission
            )
        )
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert admission.locked()
        finally:
            finish.set()
            async with asyncio.timeout(2):
                while admission.locked():
                    await asyncio.sleep(0.01)

    asyncio.run(scenario())


def test_dataset_input_read_enforces_bytes_instead_of_file_stat(tmp_path: Path) -> None:
    source = tmp_path / "proof.json"
    source.write_bytes(b"x" * 9)
    with pytest.raises(RetrievalError, match="byte limit"):
        bounded_read(source, 8)


def test_large_draft_batch_preserves_completed_drafts_within_review_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding, _, _ = _binding(tmp_path)
    binding["parts"].append({**binding["parts"][0], "reference": "U2"})
    identity = {key: binding["parts"][0][key] for key in ("manufacturer", "mpn", "package")}
    symbol = {
        "schema_version": "dsvire.symbol-result.v1",
        "identity": identity,
        "pins": [{"number": str(x)} for x in range(1, 9)],
        "svg": "x" * 400,
        "citations": [{"region_id": "test"}],
    }

    async def compile(*args: object, **kwargs: object) -> dict:
        return symbol

    monkeypatch.setattr("dsvire.board_symbols.run_symbol_job", compile)
    monkeypatch.setattr("dsvire.board_symbols.DRAFT_BUDGET_BYTES", 1400)
    result = asyncio.run(
        generate_board_symbols(
            binding, ServiceConfig(data_dir=tmp_path, service_token="x" * 32), asyncio.Semaphore(1)
        )
    )
    assert result["components"][0]["status"] == "draft"
    assert result["components"][1]["status"] == "unavailable"
    assert result["components"][1]["code"] == "result_size_limit"
    assert result["publication_allowed"] is False

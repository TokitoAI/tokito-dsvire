from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pypdf import PdfWriter

from dsvire.retrieval_source_seal import (
    SourceSealError,
    acquire_source_manifest,
    manifest_sha256,
    validate_source_manifest,
    write_manifest_atomic,
)

ROOT = Path(__file__).parents[1]


class Response:
    def __init__(self, payload: bytes, url: str, headers: dict[str, str] | None = None) -> None:
        self.payload = io.BytesIO(payload)
        self.url = url
        self.headers = headers or {"content-length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self.payload.read(size)

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _pdf(text: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_metadata({"/Title": text, "/Subject": text})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _plan() -> dict[str, Any]:
    return json.loads((ROOT / "evaluation/retrieval_cycle_v2_preregistration.json").read_text())


def _plan_v3() -> dict[str, Any]:
    return json.loads((ROOT / "evaluation/retrieval_cycle_v3_preregistration.json").read_text())


def _plan_v4() -> dict[str, Any]:
    return json.loads((ROOT / "evaluation/retrieval_cycle_v4_preregistration.json").read_text())


def _consumed() -> set[str]:
    registry = json.loads((ROOT / "evaluation/visual_registry.v1.json").read_text())
    return {item["id"] for item in registry["documents"]} | {
        item["document_group"] for item in registry["documents"]
    }


def _one_family_plan() -> dict[str, Any]:
    # Production requires the frozen 12-family plan, so tests drive the full cycle
    # using a deterministic response for every URL.
    return _plan()


def _valid_opener(request: Any, timeout: float) -> Response:
    assert timeout == 60
    url = request.full_url
    family = next(item for item in _plan()["families"] if item["official_source_url"] == url)
    return Response(_pdf(family["selected_mpn"]), url)


def _valid_v3_opener(request: Any, timeout: float) -> Response:
    assert timeout == 60
    url = request.full_url
    family = next(item for item in _plan_v3()["families"] if item["official_source_url"] == url)
    return Response(_pdf(family["selected_mpn"]), url)


def _valid_v4_opener(request: Any, timeout: float) -> Response:
    assert timeout == 60
    url = request.full_url
    family = next(item for item in _plan_v4()["families"] if item["official_source_url"] == url)
    return Response(_pdf(family["selected_mpn"]), url)


def test_cycle_v3_is_an_explicit_frozen_acquisition_boundary(tmp_path: Path) -> None:
    v2_ids = {family["id"] for family in _plan()["families"]}
    result = acquire_source_manifest(
        _plan_v3(),
        cache_dir=tmp_path,
        consumed_family_ids=_consumed() | v2_ids,
        open_url=_valid_v3_opener,
        retry_delay_seconds=0,
    )
    assert result["complete"] is True
    assert result["plan_sha256"] == (
        "2034c81f041d547249bed9e7e606d2255af0b5df32ebfda7ad025a8c917d7ccf"
    )
    assert len(result["sources"]) == 12


def test_cycle_v4_is_an_explicit_frozen_acquisition_boundary(tmp_path: Path) -> None:
    prior_ids = {family["id"] for plan in (_plan(), _plan_v3()) for family in plan["families"]}
    result = acquire_source_manifest(
        _plan_v4(),
        cache_dir=tmp_path,
        consumed_family_ids=_consumed() | prior_ids,
        open_url=_valid_v4_opener,
        retry_delay_seconds=0,
    )
    assert result["complete"] is True
    assert result["plan_sha256"] == (
        "cd7b1bd89d0e3d382eb7ea0af97107ca6931b3cd49a34964e18e4cef9dbb8acb"
    )
    assert len(result["sources"]) == 12


def test_cycle_acquisition_is_deterministic_atomic_and_download_only(tmp_path: Path) -> None:
    first = acquire_source_manifest(
        _one_family_plan(),
        cache_dir=tmp_path / "cache",
        consumed_family_ids=_consumed(),
        open_url=_valid_opener,
        retry_delay_seconds=0,
    )
    second = acquire_source_manifest(
        _one_family_plan(),
        cache_dir=tmp_path / "cache2",
        consumed_family_ids=_consumed(),
        open_url=_valid_opener,
        retry_delay_seconds=0,
    )
    assert first == second
    assert first["complete"] is True
    assert len(first["sources"]) == 12
    assert first["invalidations"] == []
    assert first["manifest_sha256"] == manifest_sha256(first)
    schema = json.loads(
        (ROOT / "scripts/schema/retrieval_cycle_source_manifest_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(first, schema)
    validate_source_manifest(
        first, expected_family_ids={item["id"] for item in _plan()["families"]}
    )
    assert {source["redistribution"] for source in first["sources"]} == {"download_only"}
    destination = tmp_path / "manifest.json"
    write_manifest_atomic(first, destination)
    assert json.loads(destination.read_text()) == first
    assert sorted(path.name for path in (tmp_path / "cache").glob("*.pdf")) == sorted(
        f"{source['content_sha256']}.pdf" for source in first["sources"]
    )
    assert not list((tmp_path / "cache").glob("*.tmp"))


@pytest.mark.parametrize(
    "payload,headers,message",
    [
        (b"<html>no</html>", None, "not a PDF"),
        (b"%PDF-broken", None, "PDF parsing failed"),
        (_pdf("unrelated document"), None, "identity was not found"),
        (_pdf("TCA9548APWR"), {"content-length": "70000000"}, "outside bounds"),
        (_pdf("TCA9548APWR"), {"content-length": "not-an-int"}, "invalid content-length"),
        (_pdf("TCA9548APWR"), {"content-length": "9999"}, "source was truncated"),
    ],
)
def test_invalid_official_source_is_recorded_without_partial_file(
    tmp_path: Path, payload: bytes, headers: dict[str, str] | None, message: str
) -> None:
    first_url = _plan()["families"][0]["official_source_url"]

    def opener(request: Any, timeout: float) -> Response:
        if request.full_url == first_url:
            return Response(payload, request.full_url, headers)
        return _valid_opener(request, timeout)

    result = acquire_source_manifest(
        _plan(),
        cache_dir=tmp_path,
        consumed_family_ids=_consumed(),
        open_url=opener,
        retry_delay_seconds=0,
    )
    assert result["complete"] is False
    assert len(result["sources"]) == 11
    assert result["invalidations"][0]["id"] == "ti-tca9548a-rev-h"
    assert message in result["invalidations"][0]["reason"]
    assert not list(tmp_path.glob("*.tmp"))


def test_final_non_https_url_is_invalidated(tmp_path: Path) -> None:
    first_url = _plan()["families"][0]["official_source_url"]

    def opener(request: Any, timeout: float) -> Response:
        if request.full_url == first_url:
            return Response(_pdf("TCA9548APWR"), "http://www.ti.com/source.pdf")
        return _valid_opener(request, timeout)

    result = acquire_source_manifest(
        _plan(),
        cache_dir=tmp_path,
        consumed_family_ids=_consumed(),
        open_url=opener,
        retry_delay_seconds=0,
    )
    assert "final source URL is not HTTPS" in result["invalidations"][0]["reason"]


def test_altered_plan_and_tampered_manifest_fail_closed(tmp_path: Path) -> None:
    altered = deepcopy(_plan())
    altered["parent_issue"] = "https://github.com/TokitoAI/tokito/issues/999"
    with pytest.raises(SourceSealError, match="altered or unrecognized"):
        acquire_source_manifest(altered, cache_dir=tmp_path, consumed_family_ids=_consumed())
    manifest = acquire_source_manifest(
        _plan(),
        cache_dir=tmp_path,
        consumed_family_ids=_consumed(),
        open_url=_valid_opener,
        retry_delay_seconds=0,
    )
    manifest["sources"][0]["bytes"] += 1
    with pytest.raises(SourceSealError, match="digest is invalid"):
        write_manifest_atomic(manifest, tmp_path / "manifest.json")


def test_manifest_contains_no_local_paths_or_source_bytes(tmp_path: Path) -> None:
    result = acquire_source_manifest(
        _plan(),
        cache_dir=tmp_path,
        consumed_family_ids=_consumed(),
        open_url=_valid_opener,
        retry_delay_seconds=0,
    )
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert "%PDF" not in serialized
    assert all(len(source["content_sha256"]) == 64 for source in result["sources"])


def test_duplicate_source_bytes_are_rejected(tmp_path: Path) -> None:
    shared = _pdf("TCA9548APWR ADXL345BCCZ")

    def opener(request: Any, timeout: float) -> Response:
        first_two = {item["official_source_url"] for item in _plan()["families"][:2]}
        if request.full_url in first_two:
            return Response(shared, "https://official.example/shared.pdf")
        return _valid_opener(request, timeout)

    with pytest.raises(SourceSealError, match="duplicate official source"):
        acquire_source_manifest(
            _plan(),
            cache_dir=tmp_path,
            consumed_family_ids=_consumed(),
            open_url=opener,
            attempts=1,
        )

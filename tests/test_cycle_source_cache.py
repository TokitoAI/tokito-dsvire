from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dsvire.cycle_source_cache import family_ids_from_plan, materialize_sealed_cycle_pdfs
from dsvire.eval_download import EvaluationDownloadError
from dsvire.retrieval_source_seal import manifest_sha256

PAYLOAD = b"%PDF-1.4\n" + b"x" * 64
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def _plan() -> dict[str, object]:
    return {"families": [{"id": "ti-bq24075"}]}


def _manifest() -> dict[str, object]:
    unsigned = {
        "schema_version": "dsvire.retrieval-cycle-source-manifest.v1",
        "plan_id": "test-plan",
        "plan_sha256": "a" * 64,
        "complete": True,
        "invalidations": [],
        "sources": [
            {
                "id": "ti-bq24075",
                "split": "calibration",
                "requested_url": "https://www.ti.com/lit/ds/symlink/bq24075.pdf",
                "final_url": "https://www.ti.com/lit/ds/symlink/bq24075.pdf",
                "bytes": len(PAYLOAD),
                "content_sha256": DIGEST,
                "identity_markers": ["bq24075"],
                "redistribution": "download_only",
                "status": "sealed",
            }
        ],
    }
    return {**unsigned, "manifest_sha256": manifest_sha256(unsigned)}


def test_family_ids_from_plan() -> None:
    assert family_ids_from_plan(_plan()) == {"ti-bq24075"}


def test_materialize_uses_cached_sealed_bytes(tmp_path: Path) -> None:
    cache = tmp_path / "sources"
    cache.mkdir()
    (cache / f"{DIGEST}.pdf").write_bytes(PAYLOAD)
    paths = materialize_sealed_cycle_pdfs(
        _manifest(), cache, expected_family_ids={"ti-bq24075"}, offline=True
    )
    assert paths == (cache / f"{DIGEST}.pdf",)
    assert paths[0].read_bytes() == PAYLOAD


def test_offline_missing_pdf_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDownloadError, match="not cached"):
        materialize_sealed_cycle_pdfs(
            _manifest(), tmp_path / "empty", expected_family_ids={"ti-bq24075"}, offline=True
        )

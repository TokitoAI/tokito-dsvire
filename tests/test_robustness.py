from __future__ import annotations

import json
from pathlib import Path

import pytest

from dsvire.robustness import (
    DEFAULT_MANIFEST,
    RobustnessError,
    generate_case,
    load_corpus,
    run_corpus,
)


def test_manifest_is_complete_unique_and_relations_are_valid() -> None:
    corpus = load_corpus()
    assert len(corpus.cases) == 11
    assert {case.recipe for case in corpus.cases} == {
        "born_digital",
        "rotated_90",
        "scan_only",
        "encrypted",
        "truncated_xref",
        "partial_download",
        "byte_limit_plus_one",
        "page_limit_plus_one",
        "render_geometry_limit",
        "changed_revision",
    }
    assert len(corpus.manifest_sha256) == 64


def test_generated_inputs_are_deterministic() -> None:
    for case in load_corpus().cases:
        assert generate_case(case) == generate_case(case), case.case_id


def test_complete_corpus_passes_and_emits_bounded_results() -> None:
    report = run_corpus()
    assert report["ok"] is True
    assert report["case_count"] == 11
    assert len(report["cases"]) == 11
    assert all(len(result["source_sha256"]) == 64 for result in report["cases"])
    assert all("error" not in result for result in report["cases"])


def test_manifest_drift_fails_closed(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    manifest["cases"][0]["recipe"] = "unknown"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RobustnessError, match="unknown robustness recipe"):
        load_corpus(path)


def test_expected_outcome_drift_fails_closed(tmp_path: Path) -> None:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    scan = next(case for case in manifest["cases"] if case["id"] == "scan-only-no-ocr")
    scan["error"] = "wrong stable reason"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RobustnessError, match="rejection drifted"):
        run_corpus(path)

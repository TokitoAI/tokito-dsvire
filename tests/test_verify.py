"""Unit tests for scripts/verify.py.

Baselines are hand-constructed shapes that match docs/CONTRACTS.md exactly.
Each negative test flips exactly one field and asserts the corresponding
Finding fails. These tests fabricate structured inputs to exercise verifier
logic — they do not fabricate any pipeline artifact on disk.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify  # noqa: E402
from verify import Outcome  # noqa: E402

# ---------------------------------------------------------------------------
# Baselines matching CONTRACTS.md exactly
# ---------------------------------------------------------------------------

BUNDLE: dict = {
    "schema_version": "dsvire.symbol-evidence.v1",
    "datasheet": {
        "id": "st-ds-h743-r09",
        "content_sha256": "b" * 64,
        "manufacturer": "STMicroelectronics",
        "mpn": "STM32H743VIT6",
        "package": "LQFP100",
    },
    "regions": [
        {
            "region_id": "r_pinout_01",
            "type": "pinout",
            "page": 42,
            "bbox_norm": [0.08, 0.12, 0.92, 0.71],
            "crop_uri": "dsvire://fixture/stm32h743vit6/r_pinout_01.webp",
            "content_hash": "sha256:" + "a" * 64,
            "verified": True,
            "verify_confidence": 0.97,
        },
        {
            "region_id": "r_pin_table_01",
            "type": "table",
            "page": 44,
            "bbox_norm": [0.10, 0.08, 0.90, 0.94],
            "crop_uri": "dsvire://fixture/stm32h743vit6/r_pin_table_01.webp",
            "content_hash": "sha256:" + "c" * 64,
            "verified": True,
            "verify_confidence": 0.94,
        },
    ],
    "retrieval": {
        "index_version": "fixture@1",
        "model_ids": ["fixture"],
        "query_ids": ["q_pinout", "q_pin_table"],
    },
}

SPEC: dict = {
    "schema_version": "tokito.symbol-spec.v1",
    "manufacturer": "STMicroelectronics",
    "mpn": "STM32H743VIT6",
    "package": "LQFP100",
    "reference_prefix": "U",
    "pins": [
        {
            "number": "1",
            "name": "PE2",
            "electrical": "bidirectional",
            "style": "line",
            "group": "gpio_e",
            "unit": 1,
            "hidden": False,
            "confidence": 0.98,
            "evidence_region_ids": ["r_pinout_01", "r_pin_table_01"],
        },
        {
            "number": "2",
            "name": "PE3",
            "electrical": "bidirectional",
            "style": "line",
            "group": "gpio_e",
            "unit": 1,
            "hidden": False,
            "confidence": 0.97,
            "evidence_region_ids": ["r_pinout_01", "r_pin_table_01"],
        },
    ],
    "properties": {
        "datasheet": "https://www.st.com/resource/en/datasheet/stm32h743vi.pdf",
        "description": "High-performance MCU, Arm Cortex-M7",
        "footprint": "",
        "keywords": "mcu cortex-m7 stm32",
    },
    "provenance": {
        "evidence_datasheet_id": "st-ds-h743-r09",
        "evidence_content_sha256": "b" * 64,
        "extractor_version": "tokito-ai.symbol-extractor@0.1.0",
        "model": "claude-sonnet-4-6",
        "extracted_at": "2026-08-08T07:12:00Z",
    },
}


PROVENANCE: dict = {
    "revision_id": "gen_sha256_ab12cd34",
    "part_id": {
        "manufacturer_norm": "stmicroelectronics",
        "mpn": "STM32H743VIT6",
        "package": "LQFP100",
    },
    "library_id": {
        "lib": "generated:stmicroelectronics",
        "name": "STM32H743VIT6",
    },
    "evidence": {
        "datasheet_id": "st-ds-h743-r09",
        "content_sha256": "b" * 64,
        "region_ids": ["r_pinout_01", "r_pin_table_01"],
    },
    "pipeline": {
        "extractor_version": "tokito-ai.symbol-extractor@0.1.0",
        "compiler_version": "tokito-catalog.compiler@0.1.0",
        "layout_policy_version": "layout@0.1.0",
        "extractor_model": "claude-sonnet-4-6",
        "dsvire_index_version": "fixture@1",
        "dsvire_model_ids": ["fixture"],
    },
    "status": "published",
    "published_at": "2026-08-08T07:15:00Z",
    "content_hash": "sha256:" + "c" * 64,
}


RESOLVED: dict = {
    "lib": "generated:stmicroelectronics",
    "name": "STM32H743VIT6",
    "body": {
        "pins": [
            {"number": "1"},
            {"number": "2"},
        ],
    },
    "properties": [],
}


def _bundle() -> dict:
    return copy.deepcopy(BUNDLE)


def _spec() -> dict:
    return copy.deepcopy(SPEC)


def _provenance() -> dict:
    return copy.deepcopy(PROVENANCE)


def _resolved() -> dict:
    return copy.deepcopy(RESOLVED)


def _find(findings: list[verify.Finding], check_id: str) -> verify.Finding:
    for f in findings:
        if f.check_id == check_id:
            return f
    raise AssertionError(f"no finding for {check_id!r} in {[f.check_id for f in findings]}")


# ---------------------------------------------------------------------------
# Evidence bundle
# ---------------------------------------------------------------------------


def test_bundle_baseline_passes() -> None:
    findings = verify.verify_evidence_bundle(_bundle())
    assert all(f.ok for f in findings), findings


def test_bundle_rejects_unverified_only_pinout() -> None:
    b = _bundle()
    b["regions"][0]["verified"] = False
    findings = verify.verify_evidence_bundle(b)
    assert _find(findings, "evidence.has_verified_pinout").outcome is Outcome.FAIL


def test_bundle_rejects_missing_table() -> None:
    b = _bundle()
    b["regions"] = [b["regions"][0]]  # only pinout
    findings = verify.verify_evidence_bundle(b)
    assert _find(findings, "evidence.has_verified_table").outcome is Outcome.FAIL


def test_bundle_rejects_extra_top_field() -> None:
    b = _bundle()
    b["junk"] = 1
    findings = verify.verify_evidence_bundle(b)
    assert _find(findings, "evidence.schema").outcome is Outcome.FAIL


# ---------------------------------------------------------------------------
# Symbol spec
# ---------------------------------------------------------------------------


def test_spec_baseline_passes() -> None:
    findings = verify.verify_symbol_spec(_spec(), _bundle())
    assert all(f.ok for f in findings), findings


def test_spec_rejects_manufacturer_mismatch() -> None:
    s = _spec()
    s["manufacturer"] = "ST Microelectronics"  # different spelling
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.manufacturer_matches_bundle").outcome is Outcome.FAIL


def test_spec_rejects_mpn_mismatch() -> None:
    s = _spec()
    s["mpn"] = "STM32H743ZIT6"
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.mpn_matches_bundle").outcome is Outcome.FAIL


def test_spec_rejects_orphan_evidence_region() -> None:
    s = _spec()
    s["pins"][0]["evidence_region_ids"] = ["r_pinout_01", "r_ghost_99"]
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.evidence_regions_present").outcome is Outcome.FAIL


def test_spec_rejects_provenance_datasheet_id_mismatch() -> None:
    s = _spec()
    s["provenance"]["evidence_datasheet_id"] = "wrong-id"
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.provenance_datasheet_matches").outcome is Outcome.FAIL


def test_spec_rejects_provenance_content_hash_mismatch() -> None:
    s = _spec()
    s["provenance"]["evidence_content_sha256"] = "d" * 64
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.provenance_content_hash_matches").outcome is Outcome.FAIL


def test_spec_rejects_duplicate_pin_numbers() -> None:
    s = _spec()
    s["pins"][1]["number"] = "1"
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.pin_numbers_unique").outcome is Outcome.FAIL


def test_spec_rejects_low_confidence_pin() -> None:
    s = _spec()
    s["pins"][0]["confidence"] = 0.5
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.pin_confidence_floor").outcome is Outcome.FAIL


def test_spec_schema_rejects_bad_electrical() -> None:
    s = _spec()
    s["pins"][0]["electrical"] = "power"  # not in enum
    findings = verify.verify_symbol_spec(s, _bundle())
    assert _find(findings, "spec.schema").outcome is Outcome.FAIL


# ---------------------------------------------------------------------------
# .tokito_sym compiled artifact
# ---------------------------------------------------------------------------

TOKITO_SYM_VALID_MINIMAL = """
(kicad_symbol_lib
  (version 20250115)
  (generator tokito-symbol-compile@0.1.0)
  (symbol "STM32H743VIT6"
    (property "Reference" "U" (id 0))
    (property "Value" "STM32H743VIT6" (id 1))
    (property "Datasheet" "https://www.st.com/resource/en/datasheet/stm32h743vi.pdf" (id 2))
    (property "Description" "High-performance MCU, Arm Cortex-M7" (id 3))
    (property "Footprint" "" (id 4))
    (property "MPN" "STM32H743VIT6" (id 5))
    (property "Manufacturer" "STMicroelectronics" (id 6))
    (property "package" "LQFP100" (id 7))
  )
)
""".strip()


def test_symbol_file_baseline_passes(tmp_path: Path) -> None:
    p = tmp_path / "symbol.tokito_sym"
    p.write_text(TOKITO_SYM_VALID_MINIMAL, encoding="utf-8")
    findings = verify.verify_symbol_file(p, _spec())
    assert all(f.ok for f in findings), findings


def test_symbol_file_missing_is_missing(tmp_path: Path) -> None:
    findings = verify.verify_symbol_file(tmp_path / "nope.tokito_sym", _spec())
    assert _find(findings, "symbol.file_exists").outcome is Outcome.MISSING


def test_symbol_file_rejects_wrong_mpn(tmp_path: Path) -> None:
    p = tmp_path / "symbol.tokito_sym"
    p.write_text(
        TOKITO_SYM_VALID_MINIMAL.replace(
            '(property "MPN" "STM32H743VIT6"',
            '(property "MPN" "STM32H743ZIT6"',
        ),
        encoding="utf-8",
    )
    findings = verify.verify_symbol_file(p, _spec())
    assert _find(findings, "symbol.mpn_literal").outcome is Outcome.FAIL


def test_symbol_file_rejects_missing_manufacturer_property(tmp_path: Path) -> None:
    p = tmp_path / "symbol.tokito_sym"
    p.write_text(
        "\n".join(
            line
            for line in TOKITO_SYM_VALID_MINIMAL.splitlines()
            if 'property "Manufacturer"' not in line
        ),
        encoding="utf-8",
    )
    findings = verify.verify_symbol_file(p, _spec())
    assert _find(findings, "symbol.canonical_properties").outcome is Outcome.FAIL


def test_symbol_file_rejects_wrong_package(tmp_path: Path) -> None:
    p = tmp_path / "symbol.tokito_sym"
    p.write_text(
        TOKITO_SYM_VALID_MINIMAL.replace(
            '(property "package" "LQFP100"',
            '(property "package" "LQFP144"',
        ),
        encoding="utf-8",
    )
    findings = verify.verify_symbol_file(p, _spec())
    assert _find(findings, "symbol.package_literal").outcome is Outcome.FAIL


# ---------------------------------------------------------------------------
# Provenance record
# ---------------------------------------------------------------------------


def test_provenance_baseline_passes() -> None:
    findings = verify.verify_provenance(_provenance(), _bundle(), _spec())
    assert all(f.ok for f in findings), findings


def test_provenance_rejects_wrong_mpn() -> None:
    p = _provenance()
    p["part_id"]["mpn"] = "STM32H743ZIT6"
    findings = verify.verify_provenance(p, _bundle(), _spec())
    assert _find(findings, "provenance.mpn_matches_spec").outcome is Outcome.FAIL


def test_provenance_rejects_wrong_package() -> None:
    p = _provenance()
    p["part_id"]["package"] = "LQFP144"
    findings = verify.verify_provenance(p, _bundle(), _spec())
    assert _find(findings, "provenance.package_matches_spec").outcome is Outcome.FAIL


def test_provenance_rejects_orphan_region_id() -> None:
    p = _provenance()
    p["evidence"]["region_ids"] = ["r_ghost_99"]
    findings = verify.verify_provenance(p, _bundle(), _spec())
    assert _find(findings, "provenance.regions_present_in_bundle").outcome is Outcome.FAIL


def test_provenance_rejects_content_hash_mismatch() -> None:
    p = _provenance()
    p["evidence"]["content_sha256"] = "d" * 64
    findings = verify.verify_provenance(p, _bundle(), _spec())
    assert _find(findings, "provenance.content_hash_matches_bundle").outcome is Outcome.FAIL


def test_provenance_rejects_non_published_status() -> None:
    p = _provenance()
    p["status"] = "quarantined"
    findings = verify.verify_provenance(p, _bundle(), _spec())
    assert _find(findings, "provenance.status_published").outcome is Outcome.FAIL


def test_provenance_schema_rejects_bad_status_value() -> None:
    p = _provenance()
    p["status"] = "shipping"
    findings = verify.verify_provenance(p, _bundle(), _spec())
    assert _find(findings, "provenance.schema").outcome is Outcome.FAIL


# ---------------------------------------------------------------------------
# Resolved symbol (MCP response)
# ---------------------------------------------------------------------------


def test_resolved_baseline_passes() -> None:
    findings = verify.verify_resolved_symbol(_resolved(), _spec())
    assert all(f.ok for f in findings), findings


def test_resolved_rejects_official_lib_prefix() -> None:
    r = _resolved()
    r["lib"] = "official:MCU_ST_STM32H7"
    findings = verify.verify_resolved_symbol(r, _spec())
    assert _find(findings, "resolved.lib_generated_namespace").outcome is Outcome.FAIL


def test_resolved_rejects_missing_pin() -> None:
    r = _resolved()
    r["body"]["pins"] = [{"number": "1"}]  # drops pin 2
    findings = verify.verify_resolved_symbol(r, _spec())
    assert _find(findings, "resolved.pins_superset_of_spec").outcome is Outcome.FAIL


def test_resolved_rejects_shape_missing_body() -> None:
    r = _resolved()
    del r["body"]
    findings = verify.verify_resolved_symbol(r, _spec())
    assert _find(findings, "resolved.shape").outcome is Outcome.FAIL


# ---------------------------------------------------------------------------
# End-to-end aggregator
# ---------------------------------------------------------------------------


def test_verify_slice_missing_stages_reports_missing(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(__import__("json").dumps(_bundle()), encoding="utf-8")
    paths = verify.ArtifactPaths(
        bundle=bundle_path,
        spec=tmp_path / "spec.json",
        symbol=tmp_path / "symbol.tokito_sym",
        provenance=tmp_path / "provenance.json",
        resolved=tmp_path / "resolved.json",
    )
    report = verify.verify_slice(paths)
    assert not report.ok
    outcomes = {f.check_id: f.outcome for f in report.findings}
    assert outcomes["spec.file_exists"] is Outcome.MISSING


def test_verify_slice_full_happy_path(tmp_path: Path) -> None:
    import json as _json

    (tmp_path / "bundle.json").write_text(_json.dumps(_bundle()), encoding="utf-8")
    (tmp_path / "spec.json").write_text(_json.dumps(_spec()), encoding="utf-8")
    (tmp_path / "symbol.tokito_sym").write_text(TOKITO_SYM_VALID_MINIMAL, encoding="utf-8")
    (tmp_path / "provenance.json").write_text(_json.dumps(_provenance()), encoding="utf-8")
    (tmp_path / "resolved.json").write_text(_json.dumps(_resolved()), encoding="utf-8")
    paths = verify.ArtifactPaths(
        bundle=tmp_path / "bundle.json",
        spec=tmp_path / "spec.json",
        symbol=tmp_path / "symbol.tokito_sym",
        provenance=tmp_path / "provenance.json",
        resolved=tmp_path / "resolved.json",
    )
    report = verify.verify_slice(paths)
    assert report.ok, [(f.check_id, f.outcome.value, f.detail) for f in report.findings if not f.ok]

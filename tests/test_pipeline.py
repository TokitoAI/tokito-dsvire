from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest

from dsvire.pipeline import DatasheetIdentity, RetrievalError, score_candidate


def _synthetic_datasheet(
    *,
    manufacturer: str = "Acme",
    mpn: str = "A-1",
    package: str = "SOIC-8",
    identity_text: str | None = None,
) -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    pinout = document.new_page()
    pinout.insert_text(
        (72, 72),
        f"{identity_text or f'{manufacturer} {mpn} {package}'}\nPin Configuration - top view\n"
        "VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
    )
    table = document.new_page()
    table.insert_text(
        (72, 72),
        "Pin Functions\nPin Name Type Description\n1 VIN input\n2 BOOT passive\n3 PH output\n4 GND ground\n5 VSENSE input\n6 ENA input\n7 COMP passive\n8 PWRPAD ground",
    )
    payload = document.tobytes()
    document.close()
    return payload


def test_pinout_verifier_accepts_real_pin_signals() -> None:
    score, verified = score_candidate(
        "pinout",
        "Figure 4-1. 8-pin package top view. VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
    )
    assert verified
    assert score >= 0.70


def test_pin_table_verifier_rejects_heading_without_rows() -> None:
    score, verified = score_candidate("table", "Table 4-1. Pin Functions Name Description")
    assert not verified
    assert score < 0.72


def test_verifier_does_not_count_arbitrary_uppercase_words_as_pins() -> None:
    _score, verified = score_candidate(
        "pinout",
        "PIN CONFIGURATION IMPORTANT INFORMATION PACKAGE DEVICE FEATURES",
    )
    assert not verified


def test_identity_is_never_guessed() -> None:
    with pytest.raises(RetrievalError, match="mpn is required"):
        DatasheetIdentity("Texas Instruments", "", "SOIC-8").validate()


def test_non_pdf_fails_before_parser(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    with pytest.raises(RetrievalError, match="not a PDF"):
        retrieve_symbol_evidence(
            b"not-pdf-data",
            DatasheetIdentity("Acme", "A-1", "SOIC-8"),
            tmp_path,
        )


def test_identical_concurrent_requests_publish_one_complete_pack(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    identity = DatasheetIdentity("Acme", "A-1", "SOIC-8")
    pdf = _synthetic_datasheet()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(retrieve_symbol_evidence, pdf, identity, tmp_path) for _ in range(2)]
    first, second = [future.result(timeout=10) for future in futures]
    assert first == second
    packs = [path for path in tmp_path.iterdir() if path.is_dir() and path.name != ".locks"]
    assert len(packs) == 1
    assert (packs[0] / "evidence.json").is_file()
    assert len(list((packs[0] / "crops").glob("*.webp"))) == 3


def test_cache_key_includes_exact_part_identity(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pdf = _synthetic_datasheet()
    first = retrieve_symbol_evidence(pdf, DatasheetIdentity("Acme", "A-1", "SOIC-8"), tmp_path)
    with pytest.raises(RetrievalError, match="exact token-bounded MPN"):
        retrieve_symbol_evidence(pdf, DatasheetIdentity("Acme", "A-2", "SOIC-8"), tmp_path)
    assert len(first["regions"]) == 3
    package = next(region for region in first["regions"] if region["type"] == "package")
    assert package["verified"] is True
    assert package["region_id"] == "r_package_01"
    schema = json.loads(
        (Path(__file__).parents[1] / "scripts/schema/symbol_evidence_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(first, schema)


def test_identity_rejects_mpn_prefix_near_miss(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pdf = _synthetic_datasheet(mpn="A-10")
    with pytest.raises(RetrievalError, match="exact token-bounded MPN"):
        retrieve_symbol_evidence(pdf, DatasheetIdentity("Acme", "A-1", "SOIC-8"), tmp_path)


def test_identity_rejects_wrong_manufacturer(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pdf = _synthetic_datasheet(manufacturer="Other Corp")
    with pytest.raises(RetrievalError, match="exact manufacturer"):
        retrieve_symbol_evidence(pdf, DatasheetIdentity("Acme", "A-1", "SOIC-8"), tmp_path)


def test_identity_rejects_package_not_associated_with_exact_mpn(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open(stream=_synthetic_datasheet(package="TSSOP-8"), filetype="pdf")
    unrelated = document.new_page()
    unrelated.insert_text((72, 72), "SOIC-8 package information for another device")
    pdf = document.tobytes()
    document.close()

    with pytest.raises(RetrievalError, match="not associated"):
        retrieve_symbol_evidence(pdf, DatasheetIdentity("Acme", "A-1", "SOIC-8"), tmp_path)


def test_identity_does_not_borrow_package_from_adjacent_variant_row(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open(stream=_synthetic_datasheet(package="SOIC-8"), filetype="pdf")
    variant_table = document.new_page()
    variant_table.insert_text((72, 72), "Acme orderable devices\nA-1 SOIC-8\nA-2 TSSOP-8")
    pdf = document.tobytes()
    document.close()

    with pytest.raises(RetrievalError, match="not associated"):
        retrieve_symbol_evidence(pdf, DatasheetIdentity("Acme", "A-1", "TSSOP-8"), tmp_path)


def test_identity_accepts_wrapped_package_tokens_within_one_part_row(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pdf = _synthetic_datasheet(
        package="SO-PowerPAD-8",
        identity_text="Acme A-1 Active Production SO PowerPAD\n(DDA) | 8",
    )
    bundle = retrieve_symbol_evidence(
        pdf, DatasheetIdentity("Acme", "A-1", "SO-PowerPAD-8"), tmp_path
    )
    assert any(region["type"] == "package" for region in bundle["regions"])


def test_invalid_cached_manifest_is_rebuilt_without_following_region_paths(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    identity = DatasheetIdentity("Acme", "A-1", "SOIC-8")
    pdf = _synthetic_datasheet()
    original = retrieve_symbol_evidence(pdf, identity, tmp_path)
    pack_name = original["regions"][0]["crop_uri"].split("/")[3]
    manifest = tmp_path / pack_name / "evidence.json"
    damaged = json.loads(manifest.read_text(encoding="utf-8"))
    damaged["regions"][0]["region_id"] = "../../outside"
    manifest.write_text(json.dumps(damaged), encoding="utf-8")

    rebuilt = retrieve_symbol_evidence(pdf, identity, tmp_path)
    assert rebuilt == original
    assert json.loads(manifest.read_text(encoding="utf-8")) == original


def test_oversized_candidate_crop_fails_before_render_allocation(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page(width=20_000, height=20_000)
    page.insert_text(
        (72, 72),
        "Acme A-1 Huge Pin Configuration top view VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7",
    )
    page.insert_text(
        (72, 10_000),
        "Pin Functions Pin Name Type Description 1 VIN 2 BOOT 3 PH 4 GND 5 VSENSE 6 ENA 7 COMP",
    )
    pdf = document.tobytes()
    document.close()

    with pytest.raises(RetrievalError, match="render safety limit"):
        retrieve_symbol_evidence(
            pdf,
            DatasheetIdentity("Acme", "A-1", "Huge"),
            tmp_path,
        )

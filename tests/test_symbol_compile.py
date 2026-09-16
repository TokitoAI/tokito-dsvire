from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from dsvire.pipeline import (
    IdentityAmbiguous,
    IdentityHint,
    RetrievalError,
    resolve_identity,
)
from dsvire.symbol_compile import compile_symbol, write_symbol_bundle
from dsvire.symbol_extract import parse_pin_table

ROOT = Path(__file__).resolve().parents[1]


def _synthetic_datasheet(
    *,
    manufacturer: str = "Acme",
    mpn: str = "A-1",
    package: str = "SOIC-8",
    extra_identity: str | None = None,
) -> bytes:
    from dsvire.pdf_fixtures import text_pdf

    identity = f"{manufacturer} {mpn} {package}"
    if extra_identity:
        identity = f"{identity}\n{extra_identity}"
    return text_pdf(
        [
            f"{identity}\nPin Configuration - top view\n"
            "VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
            "Pin Functions\nPin Name Type Description\n1 VIN input\n2 BOOT passive\n3 PH output\n4 GND ground\n5 VSENSE input\n6 ENA input\n7 COMP passive\n8 PWRPAD ground",
        ]
    )


def test_pin_table_parser_reads_numbered_rows() -> None:
    pins = parse_pin_table(
        "Pin Functions\nPin Name Type Description\n1 VIN input\n2 BOOT passive\n3 PH output\n4 GND ground"
    )
    assert [pin["number"] for pin in pins] == ["1", "2", "3", "4"]
    assert pins[0]["electrical"] == "power_in"
    assert pins[3]["electrical"] == "power_in"


def test_compile_symbol_from_unique_identity(tmp_path: Path) -> None:
    pdf = _synthetic_datasheet()
    result = compile_symbol(pdf, tmp_path, IdentityHint(), extracted_at="2026-09-17T00:00:00+00:00")
    assert result["schema_version"] == "dsvire.symbol-result.v1"
    assert result["identity"] == {"manufacturer": "Acme", "mpn": "A-1", "package": "SOIC-8"}
    assert len(result["pins"]) == 8
    assert {pin["number"] for pin in result["pins"]} == {str(index) for index in range(1, 9)}
    names = {pin["name"] for pin in result["pins"]}
    assert names == {"VIN", "BOOT", "PH", "GND", "VSENSE", "ENA", "COMP", "PWRPAD"}
    svg = result["svg"]
    for number in range(1, 9):
        assert f">{number}</text>" in svg or f">{number}<" in svg or f">{number}</text>" in svg
        assert str(number) in svg
    spec_schema = json.loads((ROOT / "scripts/schema/symbol_spec_v1.schema.json").read_text())
    result_schema = json.loads((ROOT / "scripts/schema/symbol_result_v1.schema.json").read_text())
    jsonschema.validate(result["spec"], spec_schema)
    public = {key: value for key, value in result.items() if key != "evidence"}
    jsonschema.validate(public, result_schema)
    write_symbol_bundle(result, tmp_path / "bundle")
    assert (tmp_path / "bundle" / "symbol.svg").read_text(encoding="utf-8") == svg


def test_identity_omitted_with_two_mpns_returns_candidates(tmp_path: Path) -> None:
    pdf = _synthetic_datasheet(extra_identity="Acme A-2 TSSOP-8")
    with pytest.raises(IdentityAmbiguous) as caught:
        compile_symbol(pdf, tmp_path, IdentityHint())
    mpns = {item.mpn for item in caught.value.candidates}
    assert mpns == {"A-1", "A-2"}
    chosen = compile_symbol(
        pdf, tmp_path, IdentityHint(manufacturer="Acme", mpn="A-1", package="SOIC-8")
    )
    assert chosen["identity"]["mpn"] == "A-1"


def test_missing_pin_table_abstains(tmp_path: Path) -> None:
    from dsvire.pdf_fixtures import text_pdf

    pdf = text_pdf(["Acme A-1 SOIC-8\nPin Configuration - top view VIN 1 BOOT 2 PH 3 GND 4"])
    with pytest.raises(RetrievalError, match="table"):
        compile_symbol(
            pdf, tmp_path, IdentityHint(manufacturer="Acme", mpn="A-1", package="SOIC-8")
        )


def test_resolve_identity_unique() -> None:
    identity = resolve_identity(_synthetic_datasheet(), IdentityHint())
    assert identity.mpn == "A-1"


def test_cli_compile_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from dsvire.cli import main

    pdf_path = tmp_path / "part.pdf"
    pdf_path.write_bytes(_synthetic_datasheet())
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["dsvire", "compile-symbol", str(pdf_path), "--out", str(out)])
    assert main() == 0
    assert (out / "symbol.json").is_file()
    payload = json.loads((out / "symbol.json").read_text(encoding="utf-8"))
    assert payload["pins"][0]["name"] in {
        "VIN",
        "BOOT",
        "PH",
        "GND",
        "VSENSE",
        "ENA",
        "COMP",
        "PWRPAD",
    }

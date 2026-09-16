"""PDF to standalone schematic symbol (JSON + SVG). Tokito .tokito_sym stays a later plug-in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline import (
    IdentityAmbiguous,
    IdentityHint,
    RetrievalError,
    load_verified_region_candidates,
    resolve_identity,
    retrieve_symbol_evidence,
)
from .symbol_extract import extract_symbol_spec
from .symbol_layout import compile_layout

RESULT_SCHEMA_VERSION = "dsvire.symbol-result.v1"
LAYOUT_POLICY_VERSION = "dsvire.box-layout@1.0.0"


def compile_symbol(
    pdf_bytes: bytes,
    output_root: Path,
    hint: IdentityHint | None = None,
    *,
    extracted_at: str | None = None,
) -> dict[str, Any]:
    identity = resolve_identity(pdf_bytes, hint)
    evidence = retrieve_symbol_evidence(pdf_bytes, identity, output_root)
    candidates = load_verified_region_candidates(pdf_bytes)
    table = candidates.get("table")
    if table is None:
        raise RetrievalError("no candidate region found for: table")
    spec = extract_symbol_spec(identity, table, evidence, extracted_at=extracted_at)
    laid_pins, svg = compile_layout(spec)
    citations = [
        {
            "region_id": region["region_id"],
            "type": region["type"],
            "page": region["page"],
            "bbox_norm": region["bbox_norm"],
            "content_hash": region["content_hash"],
            "crop_uri": region["crop_uri"],
        }
        for region in evidence["regions"]
    ]
    public_pins = [
        {
            "number": pin["number"],
            "name": pin["name"],
            "electrical": pin["electrical"],
            "style": pin["style"],
            "group": pin.get("group"),
            "side": pin["side"],
            "confidence": pin["confidence"],
            "evidence_region_ids": pin["evidence_region_ids"],
        }
        for pin in laid_pins
    ]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "identity": {
            "manufacturer": identity.manufacturer.strip(),
            "mpn": identity.mpn.strip(),
            "package": identity.package.strip(),
        },
        "layout_policy_version": LAYOUT_POLICY_VERSION,
        "spec": spec,
        "pins": public_pins,
        "citations": citations,
        "svg": svg,
        "evidence": evidence,
    }


def write_symbol_bundle(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (output_dir / "symbol.json").write_text(
        json.dumps(
            {key: value for key, value in result.items() if key != "evidence"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "symbol.svg").write_text(str(result["svg"]), encoding="utf-8")


def public_candidates(error: IdentityAmbiguous) -> list[dict[str, str]]:
    return [
        {
            "manufacturer": item.manufacturer,
            "mpn": item.mpn,
            "package": item.package,
        }
        for item in error.candidates
    ]

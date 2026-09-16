"""Fail-closed pin-table extraction into tokito.symbol-spec.v1 pin objects."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .pipeline import Candidate, DatasheetIdentity, RetrievalError

EXTRACTOR_VERSION = "dsvire.symbol-extractor-text@1.0.0"
SPEC_SCHEMA_VERSION = "tokito.symbol-spec.v1"
MIN_PINS = 4
MIN_CONFIDENCE = 0.6

_ROW = re.compile(
    r"^(?P<number>\d{1,4}[A-Z]?)\s+(?P<name>[A-Z][A-Z0-9_/#]*)\s+(?P<kind>[A-Za-z][A-Za-z/+_-]*)\b"
)
_HEADER = re.compile(r"^(pin|name|type|description)\b", re.I)

_ELECTRICAL = {
    "input": "input",
    "in": "input",
    "i": "input",
    "output": "output",
    "out": "output",
    "o": "output",
    "bidirectional": "bidirectional",
    "bidi": "bidirectional",
    "io": "bidirectional",
    "i/o": "bidirectional",
    "tri_state": "tri_state",
    "tristate": "tri_state",
    "passive": "passive",
    "free": "free",
    "unspecified": "unspecified",
    "power": "power_in",
    "power_in": "power_in",
    "pwr": "power_in",
    "supply": "power_in",
    "ground": "power_in",
    "gnd": "power_in",
    "power_out": "power_out",
    "open_collector": "open_collector",
    "open_emitter": "open_emitter",
    "nc": "no_connect",
    "n/c": "no_connect",
    "no_connect": "no_connect",
}

_POWER_NAMES = {"VIN", "VDD", "VCC", "V+", "VBAT", "AVDD", "DVDD", "PVIN"}
_GROUND_NAMES = {"GND", "VSS", "AGND", "DGND", "PGND", "V-", "EP", "PWRPAD", "PAD"}


class ExtractionError(RetrievalError):
    """The pin table could not be parsed without inventing pins."""


def _electrical(name: str, kind: str) -> str:
    upper = name.upper()
    if upper in _GROUND_NAMES or upper.endswith("GND"):
        return "power_in"
    if upper in _POWER_NAMES:
        return "power_in"
    if upper in {"VOUT", "SW", "PH"} and kind.casefold() in {"output", "out", "o"}:
        return "output"
    mapped = _ELECTRICAL.get(kind.casefold().replace(" ", "_"))
    if mapped:
        return mapped
    return "unspecified"


def _group(name: str, electrical: str) -> str:
    upper = name.upper()
    if upper in _GROUND_NAMES or (electrical == "power_in" and "GND" in upper):
        return "ground"
    if electrical in {"power_in", "power_out"}:
        return "power"
    if upper in {"BOOT", "COMP", "FB", "VSENSE"}:
        return "analog"
    if upper.startswith("GPIO") or re.fullmatch(r"P[A-Z]\d+", upper):
        return "gpio"
    return "signal"


def parse_pin_table(table_text: str) -> list[dict[str, Any]]:
    pins: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in table_text.splitlines():
        line = " ".join(raw.replace("\x00", " ").split())
        if not line or _HEADER.match(line.casefold()):
            continue
        match = _ROW.match(line)
        if match is None:
            continue
        number = match.group("number")
        if number in seen:
            raise ExtractionError(f"duplicate pin number {number} in pin table")
        seen.add(number)
        name = match.group("name").upper()
        electrical = _electrical(name, match.group("kind"))
        confidence = 0.86 if electrical != "unspecified" else 0.72
        if confidence < MIN_CONFIDENCE:
            raise ExtractionError("pin confidence fell below the compiler threshold")
        pins.append(
            {
                "number": number,
                "name": name,
                "electrical": electrical,
                "style": "line",
                "group": _group(name, electrical),
                "unit": 1,
                "hidden": False,
                "confidence": confidence,
                "evidence_region_ids": ["r_pinout_01", "r_pin_table_01"],
            }
        )
    if len(pins) < MIN_PINS:
        raise ExtractionError("pin table did not yield enough numbered rows")
    return pins


def extract_symbol_spec(
    identity: DatasheetIdentity,
    table: Candidate,
    evidence: dict[str, Any],
    *,
    extracted_at: str | None = None,
) -> dict[str, Any]:
    pins = parse_pin_table(table.text)
    datasheet = evidence["datasheet"]
    timestamp = extracted_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "manufacturer": identity.manufacturer.strip(),
        "mpn": identity.mpn.strip(),
        "package": identity.package.strip(),
        "reference_prefix": "U",
        "pins": pins,
        "properties": {
            "datasheet": identity.source_url or "",
            "description": f"{identity.mpn.strip()} {identity.package.strip()}",
            "footprint": "",
            "keywords": " ".join(pin["name"] for pin in pins[:12]).lower(),
        },
        "provenance": {
            "evidence_datasheet_id": datasheet["id"],
            "evidence_content_sha256": datasheet["content_sha256"],
            "extractor_version": EXTRACTOR_VERSION,
            "model": "text-layout-heuristic",
            "extracted_at": timestamp,
        },
    }

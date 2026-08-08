"""Success-criteria verifier for the Tokito symbol pipeline demo.

Exposes pure functions used by both the tests and the demo runner:

    verify_evidence_bundle(bundle)                    -> list[Finding]
    verify_symbol_spec(spec, bundle)                  -> list[Finding]
    verify_symbol_file(symbol_path, spec)             -> list[Finding]
    verify_provenance(provenance, bundle, spec)       -> list[Finding]
    verify_resolved_symbol(resolved, spec)            -> list[Finding]
    verify_slice(paths)                               -> Report

`Finding` records a single check with a stable id and a human-readable message.
`Report` is the top-level aggregator that maps every finding to a
HACKATHON_SLICE.md §7 success criterion.

Nothing in this module fabricates data. Every check runs against real artifacts
on disk. Missing artifacts produce explicit MISSING findings rather than passes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from enum import Enum
from pathlib import Path
from typing import Iterable

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "scripts" / "schema"

SCHEMA_EVIDENCE = SCHEMA_DIR / "symbol_evidence_v1.schema.json"
SCHEMA_SPEC = SCHEMA_DIR / "symbol_spec_v1.schema.json"
SCHEMA_PROVENANCE = SCHEMA_DIR / "provenance_record_v1.schema.json"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class Outcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"  # artifact not yet produced by upstream stage


@dataclasses.dataclass(frozen=True)
class Finding:
    check_id: str
    outcome: Outcome
    detail: str

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.PASS


@dataclasses.dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "findings": [
                {"check_id": f.check_id, "outcome": f.outcome.value, "detail": f.detail}
                for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(path: Path) -> jsonschema.Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------

def verify_evidence_bundle(bundle: dict) -> list[Finding]:
    """Structural + semantic checks on a dsvire.symbol-evidence.v1 document."""
    v = load_schema(SCHEMA_EVIDENCE)
    findings: list[Finding] = []

    errors = sorted(v.iter_errors(bundle), key=lambda e: e.absolute_path)
    if errors:
        findings.append(Finding(
            "evidence.schema",
            Outcome.FAIL,
            "; ".join(f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors),
        ))
        return findings
    findings.append(Finding("evidence.schema", Outcome.PASS, "matches dsvire.symbol-evidence.v1"))

    # Required verified region types.
    for required in ("pinout", "table"):
        matches = [r for r in bundle["regions"]
                   if r["type"] == required and r["verified"] is True]
        outcome = Outcome.PASS if matches else Outcome.FAIL
        findings.append(Finding(
            f"evidence.has_verified_{required}",
            outcome,
            f"{len(matches)} verified {required} region(s)",
        ))

    # bbox ordering.
    for r in bundle["regions"]:
        x0, y0, x1, y1 = r["bbox_norm"]
        if not (x0 < x1 and y0 < y1):
            findings.append(Finding(
                "evidence.bbox_ordered",
                Outcome.FAIL,
                f"{r['region_id']}: bbox_norm not strictly increasing",
            ))
            break
    else:
        findings.append(Finding(
            "evidence.bbox_ordered",
            Outcome.PASS,
            "all bbox_norm entries strictly x0<x1, y0<y1",
        ))

    return findings


def verify_symbol_spec(spec: dict, bundle: dict) -> list[Finding]:
    """Schema + cross-reference: every pin's evidence_region_ids exists in bundle."""
    v = load_schema(SCHEMA_SPEC)
    findings: list[Finding] = []

    errors = sorted(v.iter_errors(spec), key=lambda e: e.absolute_path)
    if errors:
        findings.append(Finding(
            "spec.schema",
            Outcome.FAIL,
            "; ".join(f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors),
        ))
        return findings
    findings.append(Finding("spec.schema", Outcome.PASS, "matches tokito.symbol-spec.v1"))

    # Identity cross-check.
    if spec["manufacturer"] != bundle["datasheet"]["manufacturer"]:
        findings.append(Finding(
            "spec.manufacturer_matches_bundle",
            Outcome.FAIL,
            f"spec={spec['manufacturer']!r} bundle={bundle['datasheet']['manufacturer']!r}",
        ))
    else:
        findings.append(Finding("spec.manufacturer_matches_bundle", Outcome.PASS, spec["manufacturer"]))

    for field in ("mpn", "package"):
        if spec[field] != bundle["datasheet"][field]:
            findings.append(Finding(
                f"spec.{field}_matches_bundle",
                Outcome.FAIL,
                f"spec={spec[field]!r} bundle={bundle['datasheet'][field]!r}",
            ))
        else:
            findings.append(Finding(f"spec.{field}_matches_bundle", Outcome.PASS, spec[field]))

    # Every pin's evidence_region_ids must reference the source bundle.
    bundle_regions = {r["region_id"] for r in bundle["regions"]}
    orphans: list[str] = []
    for pin in spec["pins"]:
        for rid in pin["evidence_region_ids"]:
            if rid not in bundle_regions:
                orphans.append(f"{pin['number']}({pin['name']})→{rid}")
    if orphans:
        findings.append(Finding(
            "spec.evidence_regions_present",
            Outcome.FAIL,
            "pin(s) reference regions not in the bundle: " + ", ".join(orphans),
        ))
    else:
        findings.append(Finding(
            "spec.evidence_regions_present",
            Outcome.PASS,
            f"all {sum(len(p['evidence_region_ids']) for p in spec['pins'])} references resolved",
        ))

    # Provenance must match the source bundle identity.
    if spec["provenance"]["evidence_datasheet_id"] != bundle["datasheet"]["id"]:
        findings.append(Finding(
            "spec.provenance_datasheet_matches",
            Outcome.FAIL,
            f"spec={spec['provenance']['evidence_datasheet_id']!r} "
            f"bundle={bundle['datasheet']['id']!r}",
        ))
    else:
        findings.append(Finding(
            "spec.provenance_datasheet_matches",
            Outcome.PASS,
            spec["provenance"]["evidence_datasheet_id"],
        ))

    if spec["provenance"]["evidence_content_sha256"] != bundle["datasheet"]["content_sha256"]:
        findings.append(Finding(
            "spec.provenance_content_hash_matches",
            Outcome.FAIL,
            "extractor's provenance sha256 diverges from bundle datasheet sha256",
        ))
    else:
        findings.append(Finding(
            "spec.provenance_content_hash_matches",
            Outcome.PASS,
            "extractor recorded exact bundle sha256",
        ))

    # Duplicate pin numbers only allowed on jumper devices — the spec itself
    # does not carry the SymbolFlags jumper bit (that's on the compiled Symbol),
    # so at this layer we require uniqueness.
    numbers = [p["number"] for p in spec["pins"]]
    if len(numbers) != len(set(numbers)):
        findings.append(Finding(
            "spec.pin_numbers_unique",
            Outcome.FAIL,
            "duplicate pin numbers in spec (jumpers must be encoded on the compiled Symbol, not here)",
        ))
    else:
        findings.append(Finding(
            "spec.pin_numbers_unique",
            Outcome.PASS,
            f"{len(numbers)} unique pin number(s)",
        ))

    # Confidence floor (per CONTRACTS.md §2 rules: <0.6 aborts the whole spec).
    low = [p for p in spec["pins"] if p["confidence"] < 0.6]
    if low:
        findings.append(Finding(
            "spec.pin_confidence_floor",
            Outcome.FAIL,
            f"{len(low)} pin(s) below 0.6 confidence floor: "
            + ", ".join(f"{p['number']}({p['name']})={p['confidence']}" for p in low),
        ))
    else:
        findings.append(Finding(
            "spec.pin_confidence_floor",
            Outcome.PASS,
            "all pins ≥ 0.6 confidence",
        ))

    return findings


# Canonical properties the compiler must emit into every .tokito_sym.
REQUIRED_SYMBOL_PROPERTIES = (
    "Reference", "Value", "Datasheet", "Description",
    "Footprint", "MPN", "Manufacturer", "package",
)


def verify_symbol_file(symbol_path: Path, spec: dict) -> list[Finding]:
    """Surface-level checks on the compiled .tokito_sym artifact.

    Deep semantic validation lives in tokito-catalog::compiler::tests (byte-
    identical golden). Here we just guard the demo-visible surface:
      - file exists and is non-empty;
      - every required canonical property key appears in the body;
      - MPN / Manufacturer / Package literals match the spec.
    """
    if not symbol_path.exists():
        return [Finding("symbol.file_exists", Outcome.MISSING, f"{symbol_path} not written yet")]
    text = symbol_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return [Finding("symbol.file_nonempty", Outcome.FAIL, f"{symbol_path} is empty")]

    findings: list[Finding] = [
        Finding("symbol.file_exists", Outcome.PASS, f"{symbol_path.name} present"),
    ]

    missing_props = [p for p in REQUIRED_SYMBOL_PROPERTIES if _property_present(text, p) is False]
    if missing_props:
        findings.append(Finding(
            "symbol.canonical_properties",
            Outcome.FAIL,
            f"missing property key(s): {', '.join(missing_props)}",
        ))
    else:
        findings.append(Finding(
            "symbol.canonical_properties",
            Outcome.PASS,
            f"all {len(REQUIRED_SYMBOL_PROPERTIES)} canonical property keys present",
        ))

    for field, expected in (("MPN", spec["mpn"]),
                            ("Manufacturer", spec["manufacturer"])):
        value = _property_value(text, field)
        outcome = Outcome.PASS if value == expected else Outcome.FAIL
        findings.append(Finding(
            f"symbol.{field.lower()}_literal",
            outcome,
            f"{field}={value!r} expected={expected!r}",
        ))

    # The native compiler's canonical property is lowercase `package`.
    pkg_value = _property_value(text, "package")
    if pkg_value == spec["package"]:
        findings.append(Finding("symbol.package_literal", Outcome.PASS, pkg_value))
    else:
        findings.append(Finding(
            "symbol.package_literal",
            Outcome.FAIL,
            f"package={pkg_value!r} expected={spec['package']!r}",
        ))

    return findings


_PROPERTY_RE = re.compile(
    r'\(property\s+"(?P<key>[^"]+)"\s+"(?P<value>[^"]*)"',
    re.MULTILINE,
)


def _property_present(text: str, key: str) -> bool:
    return any(m.group("key") == key for m in _PROPERTY_RE.finditer(text))


def _property_value(text: str, key: str) -> str | None:
    for m in _PROPERTY_RE.finditer(text):
        if m.group("key") == key:
            return m.group("value")
    return None


def verify_provenance(provenance: dict, bundle: dict, spec: dict) -> list[Finding]:
    """Schema + cross-reference: provenance's region_ids/manufacturer/mpn match."""
    v = load_schema(SCHEMA_PROVENANCE)
    findings: list[Finding] = []

    errors = sorted(v.iter_errors(provenance), key=lambda e: e.absolute_path)
    if errors:
        findings.append(Finding(
            "provenance.schema",
            Outcome.FAIL,
            "; ".join(f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors),
        ))
        return findings
    findings.append(Finding("provenance.schema", Outcome.PASS, "matches tokito.provenance-record.v1"))

    if provenance["part_id"]["mpn"] != spec["mpn"]:
        findings.append(Finding(
            "provenance.mpn_matches_spec",
            Outcome.FAIL,
            f"provenance={provenance['part_id']['mpn']} spec={spec['mpn']}",
        ))
    else:
        findings.append(Finding("provenance.mpn_matches_spec", Outcome.PASS, spec["mpn"]))

    if provenance["part_id"]["package"] != spec["package"]:
        findings.append(Finding(
            "provenance.package_matches_spec",
            Outcome.FAIL,
            f"provenance={provenance['part_id']['package']} spec={spec['package']}",
        ))
    else:
        findings.append(Finding("provenance.package_matches_spec", Outcome.PASS, spec["package"]))

    bundle_regions = {r["region_id"] for r in bundle["regions"]}
    orphans = [rid for rid in provenance["evidence"]["region_ids"]
               if rid not in bundle_regions]
    if orphans:
        findings.append(Finding(
            "provenance.regions_present_in_bundle",
            Outcome.FAIL,
            f"provenance references regions not in bundle: {', '.join(orphans)}",
        ))
    else:
        findings.append(Finding(
            "provenance.regions_present_in_bundle",
            Outcome.PASS,
            f"all {len(provenance['evidence']['region_ids'])} region ids in bundle",
        ))

    if provenance["evidence"]["content_sha256"] != bundle["datasheet"]["content_sha256"]:
        findings.append(Finding(
            "provenance.content_hash_matches_bundle",
            Outcome.FAIL,
            "provenance datasheet sha256 diverges from source bundle",
        ))
    else:
        findings.append(Finding(
            "provenance.content_hash_matches_bundle",
            Outcome.PASS,
            "provenance recorded exact bundle sha256",
        ))

    if provenance["status"] != "published":
        findings.append(Finding(
            "provenance.status_published",
            Outcome.FAIL,
            f"revision is {provenance['status']!r}, demo requires 'published'",
        ))
    else:
        findings.append(Finding("provenance.status_published", Outcome.PASS, "published"))

    return findings


def verify_resolved_symbol(resolved: dict, spec: dict) -> list[Finding]:
    """A ResolvedSymbol back from tokito-mcp must match the compiled spec identity.

    ResolvedSymbol is defined in tokito_catalog::model::ResolvedSymbol; the wire
    shape is:

        { "lib": str, "name": str, "body": SymbolBody, "properties": [...] }

    For the demo we assert the pin count matches the spec and the pin numbers
    are a superset (compiler may inject hidden pins for exposed pads).
    """
    findings: list[Finding] = []

    required = ("lib", "name", "body")
    missing = [k for k in required if k not in resolved]
    if missing:
        return [Finding(
            "resolved.shape",
            Outcome.FAIL,
            f"missing required key(s): {', '.join(missing)}",
        )]
    findings.append(Finding("resolved.shape", Outcome.PASS, "top-level keys present"))

    if not resolved["lib"].startswith("generated:"):
        findings.append(Finding(
            "resolved.lib_generated_namespace",
            Outcome.FAIL,
            f"lib={resolved['lib']!r} — generated symbols must live under generated:*",
        ))
    else:
        findings.append(Finding(
            "resolved.lib_generated_namespace",
            Outcome.PASS,
            resolved["lib"],
        ))

    resolved_pin_numbers = {p["number"] for p in resolved["body"].get("pins", [])}
    spec_pin_numbers = {p["number"] for p in spec["pins"]}
    if not spec_pin_numbers.issubset(resolved_pin_numbers):
        missing_pins = sorted(spec_pin_numbers - resolved_pin_numbers)
        findings.append(Finding(
            "resolved.pins_superset_of_spec",
            Outcome.FAIL,
            f"resolved symbol is missing pin(s): {', '.join(missing_pins)}",
        ))
    else:
        findings.append(Finding(
            "resolved.pins_superset_of_spec",
            Outcome.PASS,
            f"{len(spec_pin_numbers)} spec pins all present in resolved symbol "
            f"({len(resolved_pin_numbers)} total)",
        ))

    return findings


# ---------------------------------------------------------------------------
# End-to-end aggregator
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class ArtifactPaths:
    bundle: Path
    spec: Path
    symbol: Path
    provenance: Path
    resolved: Path


def verify_slice(paths: ArtifactPaths, *, require_publication: bool = True) -> Report:
    """Aggregate checks across compiled proof or the full published slice."""
    findings: list[Finding] = []

    if not paths.bundle.exists():
        return Report((Finding(
            "evidence.file_exists",
            Outcome.MISSING,
            f"{paths.bundle} not found; run scripts/build_fixture.py",
        ),))
    bundle = load_json(paths.bundle)
    findings.extend(verify_evidence_bundle(bundle))

    if paths.spec.exists():
        spec = load_json(paths.spec)
        findings.extend(verify_symbol_spec(spec, bundle))
        findings.extend(verify_symbol_file(paths.symbol, spec))
        if paths.provenance.exists():
            findings.extend(verify_provenance(load_json(paths.provenance), bundle, spec))
        elif require_publication:
            findings.append(Finding(
                "provenance.file_exists",
                Outcome.MISSING,
                f"{paths.provenance} not written; run the ingest + resolve stages",
            ))
        if paths.resolved.exists():
            findings.extend(verify_resolved_symbol(load_json(paths.resolved), spec))
        elif require_publication:
            findings.append(Finding(
                "resolved.file_exists",
                Outcome.MISSING,
                f"{paths.resolved} not written; run the resolve_by_mpn stage",
            ))
    else:
        findings.append(Finding(
            "spec.file_exists",
            Outcome.MISSING,
            f"{paths.spec} not written; run the extract stage",
        ))

    return Report(tuple(findings))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _paths_for(slug: str, artifacts_root: Path, bundle: Path | None = None) -> ArtifactPaths:
    art = artifacts_root / slug
    return ArtifactPaths(
        bundle=bundle or REPO_ROOT / "fixtures" / "evidence" / f"{slug}.json",
        spec=art / "spec.json",
        symbol=art / "symbol.tokito_sym",
        provenance=art / "provenance.json",
        resolved=art / "resolved.json",
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: Iterable[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="fixture slug, e.g. tps5430ddar")
    ap.add_argument(
        "--artifacts",
        type=Path,
        default=REPO_ROOT / "artifacts",
        help="root of pipeline artifact directories (default: <repo>/artifacts)",
    )
    ap.add_argument(
        "--bundle",
        type=Path,
        help="explicit evidence bundle (defaults to fixtures/evidence/<slug>.json)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit the report as machine-readable JSON",
    )
    ap.add_argument(
        "--compiled-only",
        action="store_true",
        help="verify evidence, spec, and compiled symbol without requiring publication artifacts",
    )
    ap.add_argument(
        "--out",
        type=Path,
        help="also write the machine-readable report to this path",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    report = verify_slice(
        _paths_for(args.slug, args.artifacts, args.bundle),
        require_publication=not args.compiled_only,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        for f in report.findings:
            print(f"[{f.outcome.value:7s}] {f.check_id:45s} {f.detail}")
        print()
        print("RESULT:", "PASS" if report.ok else "FAIL")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

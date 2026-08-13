"""Versioned, source-generated PDF robustness corpus and executable gate."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import ArrayObject, ByteStringObject

from .pdf_fixtures import add_rgb_image_page, add_text_page, text_pdf, write_pdf
from .pipeline import (
    MAX_PAGES,
    MAX_PDF_BYTES,
    DatasheetIdentity,
    RetrievalError,
    retrieve_symbol_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "fixtures" / "robustness" / "v1" / "manifest.json"
EXPECTED_SCHEMA = "dsvire.robustness-corpus.v1"
EXPECTED_GENERATOR = "dsvire.robustness-generator@1.0.0"
Outcome = Literal["accepted", "rejected", "accepted_duplicate", "accepted_revision"]
StrictParserOutcome = Literal["accepted", "encrypted", "rejected", "not_run"]


class RobustnessError(RuntimeError):
    """The corpus definition or an observed outcome failed closed."""


@dataclasses.dataclass(frozen=True)
class Case:
    case_id: str
    recipe: str
    expected: Outcome
    strict_parser: StrictParserOutcome
    error: str | None = None
    same_as: str | None = None
    different_from: str | None = None


@dataclasses.dataclass(frozen=True)
class Corpus:
    identity: DatasheetIdentity
    cases: tuple[Case, ...]
    manifest_sha256: str


def load_corpus(path: Path = DEFAULT_MANIFEST) -> Corpus:
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RobustnessError("robustness manifest is not valid JSON") from exc
    if data.get("schema_version") != EXPECTED_SCHEMA:
        raise RobustnessError("unsupported robustness manifest schema")
    if data.get("generator_version") != EXPECTED_GENERATOR:
        raise RobustnessError("unsupported robustness generator version")
    identity_data = data.get("identity")
    if not isinstance(identity_data, dict):
        raise RobustnessError("robustness identity is missing")
    identity = DatasheetIdentity(
        manufacturer=str(identity_data.get("manufacturer", "")),
        mpn=str(identity_data.get("mpn", "")),
        package=str(identity_data.get("package", "")),
    )
    identity.validate()
    case_values = data.get("cases")
    if not isinstance(case_values, list) or not case_values:
        raise RobustnessError("robustness cases are missing")
    cases: list[Case] = []
    seen: set[str] = set()
    valid_outcomes = {"accepted", "rejected", "accepted_duplicate", "accepted_revision"}
    valid_parser = {"accepted", "encrypted", "rejected", "not_run"}
    for value in case_values:
        if not isinstance(value, dict):
            raise RobustnessError("robustness case must be an object")
        case_id = str(value.get("id", ""))
        recipe = str(value.get("recipe", ""))
        expected = str(value.get("expected", ""))
        strict_parser = str(value.get("strict_parser", ""))
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case_id) or case_id in seen:
            raise RobustnessError(f"invalid or duplicate robustness case id: {case_id!r}")
        if recipe not in _RECIPES:
            raise RobustnessError(f"unknown robustness recipe: {recipe!r}")
        if expected not in valid_outcomes or strict_parser not in valid_parser:
            raise RobustnessError(f"invalid expected outcome for {case_id}")
        error = value.get("error")
        same_as = value.get("same_as")
        different_from = value.get("different_from")
        if (expected == "rejected") != isinstance(error, str):
            raise RobustnessError(f"{case_id}: rejected cases alone require an error")
        if (expected == "accepted_duplicate") != isinstance(same_as, str):
            raise RobustnessError(f"{case_id}: duplicate relation is invalid")
        if (expected == "accepted_revision") != isinstance(different_from, str):
            raise RobustnessError(f"{case_id}: revision relation is invalid")
        seen.add(case_id)
        cases.append(
            Case(
                case_id,
                recipe,
                cast(Outcome, expected),
                cast(StrictParserOutcome, strict_parser),
                cast(str | None, error),
                cast(str | None, same_as),
                cast(str | None, different_from),
            )
        )
    for case in cases:
        for relation in (case.same_as, case.different_from):
            if relation is not None and relation not in seen:
                raise RobustnessError(f"{case.case_id}: unknown related case {relation!r}")
    return Corpus(identity, tuple(cases), hashlib.sha256(raw).hexdigest())


def _born_digital(*, revision: str = "R1", rotation: int = 0) -> bytes:
    return text_pdf(
        [
            f"Acme A-1 SOIC-8 {revision}\nPin Configuration - top view\n"
            "VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
            "Pin Functions\nPin Name Type Description\n1 VIN input\n2 BOOT passive\n"
            "3 PH output\n4 GND ground\n5 VSENSE input\n6 ENA input\n"
            "7 COMP passive\n8 PWRPAD ground",
        ],
        rotations=[rotation, rotation],
    )


def _scan_only() -> bytes:
    writer = PdfWriter()
    pixels = b"\xff\xff\xff" * (800 * 500)
    for _ in range(2):
        add_rgb_image_page(writer, pixels, width=800, height=500)
    return write_pdf(writer)


def _encrypted() -> bytes:
    reader = PdfReader(io.BytesIO(_born_digital()), strict=True)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    # pypdf deliberately gives newly encrypted files random/time-derived IDs.
    # Set a fixed valid identifier before encryption so this generated corpus
    # is byte-reproducible across runs and platforms.
    fixed_id = ByteStringObject(hashlib.sha256(b"dsvire-robustness-encrypted-v1").digest()[:16])
    writer._ID = ArrayObject((fixed_id, fixed_id))
    writer.encrypt(
        "corpus-user",
        "corpus-owner",
        algorithm="RC4-128",
        permissions_flag=UserAccessPermissions(0),
    )
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _page_limit_plus_one() -> bytes:
    writer = PdfWriter()
    for _ in range(MAX_PAGES + 1):
        writer.add_blank_page(width=72, height=72)
    return write_pdf(writer)


def _render_geometry_limit() -> bytes:
    writer = PdfWriter()
    add_text_page(
        writer,
        "Acme A-1 SOIC-8 Pin Configuration top view VIN 1 BOOT 2 PH 3 GND 4 "
        "VSENSE 5 ENA 6 COMP 7 PWRPAD 8\n"
        + "\n"
        * 300
        + "Pin Functions Pin Name Type Description 1 VIN 2 BOOT 3 PH 4 GND "
        "5 VSENSE 6 ENA 7 COMP 8 PWRPAD",
        width=20_000,
        height=20_000,
    )
    return write_pdf(writer)


def _truncated_xref() -> bytes:
    return _born_digital()[:-100]


def _partial_download() -> bytes:
    payload = _born_digital()
    return payload[: max(16, len(payload) // 3)]


def _byte_limit_plus_one() -> bytes:
    base = _born_digital()
    return base + b"\n" + b"0" * (MAX_PDF_BYTES - len(base))


class Recipe(Protocol):
    def __call__(self) -> bytes: ...


_RECIPES: dict[str, Recipe] = {
    "born_digital": _born_digital,
    "rotated_90": lambda: _born_digital(rotation=90),
    "scan_only": _scan_only,
    "encrypted": _encrypted,
    "truncated_xref": _truncated_xref,
    "partial_download": _partial_download,
    "byte_limit_plus_one": _byte_limit_plus_one,
    "page_limit_plus_one": _page_limit_plus_one,
    "render_geometry_limit": _render_geometry_limit,
    "changed_revision": lambda: _born_digital(revision="R2"),
}


def generate_case(case: Case) -> bytes:
    return _RECIPES[case.recipe]()


def strict_parser_outcome(payload: bytes, expected: StrictParserOutcome) -> str:
    if expected == "not_run":
        return "not_run"
    logger = logging.getLogger("pypdf")
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted:
            observed = "encrypted"
        else:
            _ = len(reader.pages)
            observed = "accepted"
    except Exception:
        # Some pypdf releases raise while constructing an encrypted reader in
        # strict mode. A non-strict metadata-only probe distinguishes that
        # intentional access-control outcome from structural rejection; it is
        # never used to parse production evidence.
        try:
            observed = (
                "encrypted"
                if PdfReader(io.BytesIO(payload), strict=False).is_encrypted
                else "rejected"
            )
        except Exception:
            observed = "rejected"
    finally:
        logger.setLevel(previous_level)
    if observed != expected:
        raise RobustnessError(
            f"strict parser outcome drifted: expected {expected}, observed {observed}"
        )
    return observed


def run_corpus(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    corpus = load_corpus(path)
    results: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    bundles: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="dsvire-robustness-") as directory:
        root = Path(directory)
        for case in corpus.cases:
            started = time.perf_counter()
            payload = generate_case(case)
            payloads[case.case_id] = payload
            digest = hashlib.sha256(payload).hexdigest()
            parser_outcome = strict_parser_outcome(payload, case.strict_parser)
            output = root / (case.same_as or case.case_id)
            observed = "accepted"
            error = None
            try:
                bundle = retrieve_symbol_evidence(payload, corpus.identity, output)
                bundles[case.case_id] = bundle
            except RetrievalError as exc:
                observed = "rejected"
                error = str(exc)

            expected_observed = "rejected" if case.expected == "rejected" else "accepted"
            if observed != expected_observed:
                raise RobustnessError(
                    f"{case.case_id}: expected {expected_observed}, observed {observed}: {error}"
                )
            if case.error is not None and (error is None or re.search(case.error, error) is None):
                raise RobustnessError(
                    f"{case.case_id}: rejection drifted from {case.error!r}: {error!r}"
                )
            evidence_files = list(output.glob("*/evidence.json")) if output.exists() else []
            if observed == "rejected" and evidence_files:
                raise RobustnessError(f"{case.case_id}: rejected input published evidence")
            if observed == "rejected" and list(output.glob(".*.corrupt")):
                raise RobustnessError(f"{case.case_id}: rejected input left corrupt packs")
            if observed == "accepted" and len(evidence_files) != 1:
                raise RobustnessError(f"{case.case_id}: accepted input did not publish one pack")
            if case.same_as is not None and (
                payload != payloads[case.same_as] or bundles[case.case_id] != bundles[case.same_as]
            ):
                raise RobustnessError(f"{case.case_id}: exact duplicate was not idempotent")
            if case.different_from is not None:
                if payload == payloads[case.different_from]:
                    raise RobustnessError(f"{case.case_id}: changed revision bytes did not change")
                if (
                    bundles[case.case_id]["datasheet"]["content_sha256"]
                    == bundles[case.different_from]["datasheet"]["content_sha256"]
                ):
                    raise RobustnessError(
                        f"{case.case_id}: changed revision reused source identity"
                    )
            results.append(
                {
                    "case_id": case.case_id,
                    "expected": case.expected,
                    "observed": observed,
                    "strict_parser": parser_outcome,
                    "source_sha256": digest,
                    "source_bytes": len(payload),
                    "published_packs": len(evidence_files),
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                }
            )
    return {
        "schema_version": "dsvire.robustness-result.v1",
        "corpus_schema_version": EXPECTED_SCHEMA,
        "generator_version": EXPECTED_GENERATOR,
        "manifest_sha256": corpus.manifest_sha256,
        "ok": True,
        "case_count": len(results),
        "cases": results,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)

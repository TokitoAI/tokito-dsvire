"""Bounded PDF-to-evidence retrieval for the symbol-generation path.

This is the deterministic production baseline. It deliberately fails closed:
no fabricated regions and no guessed part identity. Every accepted result names
the deterministic heuristic policy that produced it; it never claims visual or
calibrated verification.
Vision model reranking can replace the scoring layer without changing the
frozen `dsvire.symbol-evidence.v2` output contract.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from .pdf_backend import BACKEND_ID, PdfBackendError, PdfDocument

MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_PAGES = 2_000
MAX_TEXT_CHARS_PER_PAGE = 250_000
RENDER_DPI = 220
MAX_RENDER_SIDE_PIXELS = 12_000
MAX_RENDER_PIXELS = 40_000_000
INDEX_VERSION = "dsvire-baseline@0.4.0"
EVIDENCE_SCHEMA_VERSION = "dsvire.symbol-evidence.v2"
IDENTITY_POLICY_VERSION = "dsvire.identity-text@2.0.0"
REGION_POLICY_VERSION = "dsvire.region-text-layout@2.0.0"
MODEL_IDS = [f"{BACKEND_ID}-layout-text@2"]
PACK_LOCK_TIMEOUT_SECONDS = 60

PINOUT_TERMS = (
    "pinout",
    "pin out",
    "pin configuration",
    "terminal configuration",
    "top view",
    "bottom view",
    "ball map",
    "pin assignment",
)
PIN_TABLE_TERMS = (
    "pin functions",
    "pin function",
    "pin description",
    "terminal functions",
    "terminal function",
    "pin name",
    "signal name",
)
TABLE_HEADER_TERMS = ("description", "function", "type", "name", "pin")
PIN_TOKEN = re.compile(
    r"(?<![A-Z0-9_])(?:"
    r"[A-Z]{1,6}[0-9]{1,3}|[0-9]{1,3}|"
    r"V(?:DD|SS|IN|OUT)|GND|AGND|DGND|EN|NC|COMP|BOOT|PH|FB|"
    r"SCL|SDA|TX|RX|RESET|NRST"
    r")(?![A-Z0-9_])"
)


class RetrievalError(RuntimeError):
    """Input or evidence quality did not satisfy the fail-closed contract."""


@dataclasses.dataclass(frozen=True)
class DatasheetIdentity:
    manufacturer: str
    mpn: str
    package: str
    source_url: str | None = None

    def validate(self) -> None:
        for name, value, limit in (
            ("manufacturer", self.manufacturer, 160),
            ("mpn", self.mpn, 120),
            ("package", self.package, 120),
        ):
            if not value.strip():
                raise RetrievalError(f"{name} is required; DS-ViRe never guesses part identity")
            if len(value.encode("utf-8")) > limit:
                raise RetrievalError(f"{name} exceeds {limit} UTF-8 bytes")


@dataclasses.dataclass(frozen=True)
class TextBlock:
    bbox: tuple[float, float, float, float]
    text: str


@dataclasses.dataclass(frozen=True)
class Candidate:
    kind: str
    page_index: int
    bbox: tuple[float, float, float, float]
    caption: str
    text: str
    score: float
    verified: bool


def _normalise_text(value: str) -> str:
    return " ".join(value.replace("\x00", " ").split())


def _normalise_phrase(value: str) -> str:
    normalised = unicodedata.normalize("NFKC", value).casefold()
    separated = "".join(character if character.isalnum() else " " for character in normalised)
    return " ".join(separated.split())


def _contains_phrase(text: str, phrase: str) -> bool:
    haystack = _normalise_phrase(text)
    needle = _normalise_phrase(phrase)
    return bool(needle) and f" {needle} " in f" {haystack} "


def _contains_ordered_tokens(text: str, phrase: str, *, max_extra_tokens: int = 2) -> bool:
    haystack = _normalise_phrase(text).split()
    needle = _normalise_phrase(phrase).split()
    if not needle:
        return False
    for start, token in enumerate(haystack):
        if token != needle[0]:
            continue
        matched = 1
        end_limit = min(len(haystack), start + len(needle) + max_extra_tokens)
        for candidate in haystack[start + 1 : end_limit]:
            if matched < len(needle) and candidate == needle[matched]:
                matched += 1
        if matched == len(needle):
            return True
    return False


def _normalise_mpn(value: str) -> str:
    normalised = unicodedata.normalize("NFKC", value).upper()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        normalised = normalised.replace(dash, "-")
    return normalised.strip()


def _contains_exact_mpn(text: str, mpn: str) -> bool:
    haystack = _normalise_mpn(text)
    needle = _normalise_mpn(mpn)
    if not needle:
        return False
    start = 0
    while (index := haystack.find(needle, start)) >= 0:
        before = haystack[index - 1] if index else ""
        end = index + len(needle)
        after = haystack[end] if end < len(haystack) else ""
        if not before.isalnum() and not after.isalnum():
            return True
        start = index + 1
    return False


def _starts_new_part_row(line: str, package: str) -> bool:
    words = line.strip().split()
    if not words:
        return False
    first = unicodedata.normalize("NFKC", words[0]).strip("()[]{}|,;:")
    if not (
        any(character.isalpha() for character in first)
        and any(character.isdigit() for character in first)
    ):
        return False
    first_norm = _normalise_phrase(first)
    package_norm = _normalise_phrase(package)
    return bool(first_norm) and not package_norm.startswith(first_norm)


def _term_hits(text: str, terms: Iterable[str]) -> int:
    lower = text.casefold()
    return sum(1 for term in terms if term in lower)


def _pin_token_count(text: str) -> int:
    return len(set(PIN_TOKEN.findall(text.upper())))


def score_candidate(kind: str, text: str) -> tuple[float, bool]:
    """Score and structurally verify a candidate without model guesswork."""
    text = _normalise_text(text)
    pins = _pin_token_count(text)
    if kind == "pinout":
        title_hits = _term_hits(text, PINOUT_TERMS)
        score = min(1.0, title_hits * 0.34 + min(pins, 12) * 0.045)
        verified = title_hits >= 1 and pins >= 4 and score >= 0.70
    elif kind == "table":
        # Several phrases intentionally overlap (for example, "pin function"
        # inside "pin functions"). Treat the heading as one signal so a bare
        # title cannot inflate itself into verified evidence.
        title_hits = min(1, _term_hits(text, PIN_TABLE_TERMS))
        header_hits = _term_hits(text, TABLE_HEADER_TERMS)
        score = min(1.0, title_hits * 0.30 + min(header_hits, 3) * 0.09 + min(pins, 16) * 0.03)
        verified = title_hits >= 1 and header_hits >= 2 and pins >= 4 and score >= 0.72
    else:
        raise ValueError(f"unsupported candidate kind: {kind}")
    return round(score, 4), verified


def _extract_blocks(page: Any) -> list[TextBlock]:
    raw = page.blocks()
    blocks: list[TextBlock] = []
    chars = 0
    for item in raw:
        text = _normalise_text(item.text)
        if not text:
            continue
        chars += len(text)
        if chars > MAX_TEXT_CHARS_PER_PAGE:
            raise RetrievalError("page text exceeds safety limit")
        x0, y0, x1, y1 = item.bbox
        blocks.append(TextBlock((x0, y0, x1, y1), text))
    return blocks


def _candidate_for_page(
    kind: str, page_index: int, page: Any, blocks: list[TextBlock]
) -> Candidate | None:
    page_rect = page.rect
    terms = PINOUT_TERMS if kind == "pinout" else PIN_TABLE_TERMS
    anchors = [block for block in blocks if _term_hits(block.text, terms)]
    if not anchors:
        return None

    # A heading plus the material immediately below it is the most stable
    # cross-vendor signal. Include the full content width so drawings and
    # multi-column pin tables remain intact, but cap the vertical window.
    anchor = max(anchors, key=lambda block: (_term_hits(block.text, terms), -block.bbox[1]))
    page_h = float(page_rect.height)
    page_w = float(page_rect.width)
    top = max(0.0, anchor.bbox[1] - page_h * 0.035)
    height = page_h * (0.34 if kind == "pinout" else 0.42)
    bottom = min(page_h, max(anchor.bbox[3] + page_h * 0.16, top + height))
    bbox = (page_w * 0.035, top, page_w * 0.965, bottom)
    nearby = "\n".join(
        block.text for block in blocks if block.bbox[3] >= top and block.bbox[1] <= bottom
    )
    score, verified = score_candidate(kind, nearby)
    return Candidate(
        kind=kind,
        page_index=page_index,
        bbox=bbox,
        caption=anchor.text[:500],
        text=nearby,
        score=score,
        verified=verified,
    )


def _best_candidates(document: Any) -> dict[str, Candidate]:
    best: dict[str, Candidate] = {}
    if document.page_count < 1 or document.page_count > MAX_PAGES:
        raise RetrievalError(f"PDF page count {document.page_count} outside 1..={MAX_PAGES}")
    for page_index in range(document.page_count):
        with document.load_page(page_index) as page:
            blocks = _extract_blocks(page)
            for kind in ("pinout", "table"):
                candidate = _candidate_for_page(kind, page_index, page, blocks)
                if candidate and (kind not in best or candidate.score > best[kind].score):
                    best[kind] = candidate
    missing = [kind for kind in ("pinout", "table") if kind not in best]
    if missing:
        raise RetrievalError(f"no candidate region found for: {', '.join(missing)}")
    unverified = [kind for kind, candidate in best.items() if not candidate.verified]
    if unverified:
        detail = ", ".join(f"{kind}={best[kind].score:.2f}" for kind in unverified)
        raise RetrievalError(f"evidence verification abstained: {detail}")
    return best


def _identity_package_candidate(document: Any, identity: DatasheetIdentity) -> Candidate:
    """Prove the requested identity from PDF text or abstain.

    Manufacturer presence is checked independently across the document. The
    exact, token-bounded MPN and requested package must occur in one logical
    orderable-part row. Wrapped continuation lines are allowed until another
    part-like row begins.
    """
    manufacturer_seen = False
    mpn_seen = False
    associations: list[Candidate] = []

    for page_index in range(document.page_count):
        with document.load_page(page_index) as page:
            raw_text = page.text()
            if len(raw_text) > MAX_TEXT_CHARS_PER_PAGE:
                raise RetrievalError("page text exceeds safety limit")
            manufacturer_seen = manufacturer_seen or _contains_phrase(
                raw_text, identity.manufacturer
            )
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            for line_index, line in enumerate(lines):
                if not _contains_exact_mpn(line, identity.mpn):
                    continue
                mpn_seen = True
                row_lines = [line]
                for continuation in lines[line_index + 1 : line_index + 4]:
                    if _starts_new_part_row(continuation, identity.package):
                        break
                    row_lines.append(continuation)
                association_text = "\n".join(row_lines)
                if not _contains_ordered_tokens(association_text, identity.package):
                    continue

                start = max(0, line_index - 1)
                end = min(len(lines), line_index + len(row_lines) + 1)
                nearby = "\n".join(lines[start:end])
                blocks = _extract_blocks(page)
                anchor = next(
                    (block for block in blocks if _contains_exact_mpn(block.text, identity.mpn)),
                    None,
                )
                page_w = float(page.rect.width)
                page_h = float(page.rect.height)
                if anchor is None:
                    top, bottom = 0.0, min(page_h, page_h * 0.22)
                else:
                    top = max(0.0, anchor.bbox[1] - page_h * 0.035)
                    bottom = min(page_h, max(anchor.bbox[3] + page_h * 0.09, top + page_h * 0.16))
                associations.append(
                    Candidate(
                        kind="package",
                        page_index=page_index,
                        bbox=(page_w * 0.035, top, page_w * 0.965, bottom),
                        caption=(
                            f"Exact identity evidence: {identity.manufacturer.strip()} "
                            f"{identity.mpn.strip()} {identity.package.strip()}"
                        ),
                        text=nearby,
                        score=1.0,
                        verified=True,
                    )
                )

    if not manufacturer_seen:
        raise RetrievalError("exact manufacturer identity is absent from PDF text")
    if not mpn_seen:
        raise RetrievalError("exact token-bounded MPN is absent from PDF text")
    if not associations:
        raise RetrievalError("requested package is not associated with the exact MPN in PDF text")
    return max(associations, key=lambda candidate: candidate.score)


def _bbox_norm(candidate: Candidate, page: Any) -> list[float]:
    width = float(page.rect.width)
    height = float(page.rect.height)
    x0, y0, x1, y1 = candidate.bbox
    return [
        round(x0 / width, 6),
        round(y0 / height, 6),
        round(x1 / width, 6),
        round(y1 / height, 6),
    ]


def _render_crop(page: Any, bbox: tuple[float, float, float, float]) -> bytes:
    from PIL import Image

    x0, y0, x1, y1 = bbox
    pixel_width = (x1 - x0) * RENDER_DPI / 72.0
    pixel_height = (y1 - y0) * RENDER_DPI / 72.0
    if (
        pixel_width <= 0
        or pixel_height <= 0
        or pixel_width > MAX_RENDER_SIDE_PIXELS
        or pixel_height > MAX_RENDER_SIDE_PIXELS
        or pixel_width * pixel_height > MAX_RENDER_PIXELS
    ):
        raise RetrievalError("candidate crop exceeds render safety limit")
    output = io.BytesIO()
    with Image.open(io.BytesIO(page.render_png(bbox, dpi=RENDER_DPI))) as image:
        image.save(output, format="WEBP", quality=90, method=6)
    return output.getvalue()


def _artifact_id(content_sha256: str, identity: DatasheetIdentity) -> str:
    """Key cached evidence by bytes, exact identity, and retrieval implementation."""
    key = {
        "content_sha256": content_sha256,
        "manufacturer": identity.manufacturer.strip(),
        "mpn": identity.mpn.strip(),
        "package": identity.package.strip(),
        "index_version": INDEX_VERSION,
        "model_ids": MODEL_IDS,
    }
    encoded = json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _load_cached_bundle(
    pack_dir: Path, identity: DatasheetIdentity, digest: str
) -> dict[str, Any] | None:
    manifest = pack_dir / "evidence.json"
    if not manifest.is_file():
        return None
    try:
        bundle = json.loads(manifest.read_text(encoding="utf-8"))
        datasheet = bundle["datasheet"]
        retrieval = bundle["retrieval"]
        if (
            bundle["schema_version"] != EVIDENCE_SCHEMA_VERSION
            or datasheet["content_sha256"] != digest
            or datasheet["manufacturer"] != identity.manufacturer.strip()
            or datasheet["mpn"] != identity.mpn.strip()
            or datasheet["package"] != identity.package.strip()
            or retrieval["index_version"] != INDEX_VERSION
            or retrieval["model_ids"] != MODEL_IDS
        ):
            return None
        regions = bundle["regions"]
        if not isinstance(regions, list) or len(regions) != 3:
            return None
        expected_regions = {
            "r_pinout_01": "pinout",
            "r_pin_table_01": "table",
            "r_package_01": "package",
        }
        seen: set[str] = set()
        identity_verification = bundle["identity_verification"]
        if identity_verification != {
            "method": "exact_text_orderable_part",
            "policy_version": IDENTITY_POLICY_VERSION,
            "outcome": "accepted",
            "manufacturer_observed": True,
            "exact_mpn_observed": True,
            "package_associated": True,
            "evidence_region_ids": ["r_package_01"],
        }:
            return None
        for region in regions:
            if not isinstance(region, dict):
                return None
            region_id = region.get("region_id")
            if (
                region_id not in expected_regions
                or region.get("type") != expected_regions[region_id]
                or region_id in seen
                or region.get("crop_uri") != f"dsvire://pack/{pack_dir.name}/{region_id}.webp"
            ):
                return None
            verification = region.get("verification")
            if not isinstance(verification, dict) or verification != {
                "method": "text_layout_heuristic",
                "policy_version": REGION_POLICY_VERSION,
                "outcome": "accepted",
                "score": verification.get("score"),
                "score_semantics": "heuristic_evidence_strength",
            }:
                return None
            score = verification["score"]
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 0 <= score <= 1
            ):
                return None
            seen.add(region_id)
            crop_path = pack_dir / "crops" / f"{region['region_id']}.webp"
            crop = crop_path.read_bytes()
            if region["content_hash"] != f"sha256:{hashlib.sha256(crop).hexdigest()}":
                return None
        if seen != set(expected_regions):
            return None
        return cast(dict[str, Any], bundle)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def retrieve_symbol_evidence(
    pdf_bytes: bytes, identity: DatasheetIdentity, output_root: Path
) -> dict[str, Any]:
    """Retrieve policy-attributed pinout, table, and package evidence."""
    identity.validate()
    if len(pdf_bytes) < 8 or len(pdf_bytes) > MAX_PDF_BYTES:
        raise RetrievalError(f"PDF size outside 8..={MAX_PDF_BYTES} bytes")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RetrievalError("input is not a PDF (missing %PDF header)")

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    pack_id = _artifact_id(digest, identity)
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_dir = output_root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    pack_dir = output_root / pack_id
    lock = FileLock(lock_dir / f"{pack_id}.lock", timeout=PACK_LOCK_TIMEOUT_SECONDS)
    try:
        with lock:
            cached = _load_cached_bundle(pack_dir, identity, digest)
            if cached is not None:
                return cached

            staging = Path(tempfile.mkdtemp(prefix=f".{pack_id}-", dir=output_root))
            try:
                crop_dir = staging / "crops"
                crop_dir.mkdir(mode=0o700)
                try:
                    document = PdfDocument(pdf_bytes)
                except PdfBackendError as exc:
                    raise RetrievalError(str(exc)) from exc
                try:
                    candidates = _best_candidates(document)
                    candidates["package"] = _identity_package_candidate(document, identity)
                    regions = []
                    for kind in ("pinout", "table", "package"):
                        candidate = candidates[kind]
                        with document.load_page(candidate.page_index) as page:
                            crop = _render_crop(page, candidate.bbox)
                            region_id = {
                                "pinout": "r_pinout_01",
                                "table": "r_pin_table_01",
                                "package": "r_package_01",
                            }[kind]
                            crop_path = crop_dir / f"{region_id}.webp"
                            crop_path.write_bytes(crop)
                            regions.append(
                                {
                                    "region_id": region_id,
                                    "type": kind,
                                    "page": candidate.page_index + 1,
                                    "bbox_norm": _bbox_norm(candidate, page),
                                    "crop_uri": f"dsvire://pack/{pack_id}/{region_id}.webp",
                                    "content_hash": f"sha256:{hashlib.sha256(crop).hexdigest()}",
                                    "verification": {
                                        "method": "text_layout_heuristic",
                                        "policy_version": REGION_POLICY_VERSION,
                                        "outcome": "accepted",
                                        "score": candidate.score,
                                        "score_semantics": "heuristic_evidence_strength",
                                    },
                                    "caption": candidate.caption,
                                }
                            )
                finally:
                    document.close()

                bundle = {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "datasheet": {
                        "id": f"ds_sha256_{digest[:24]}",
                        "content_sha256": digest,
                        "manufacturer": identity.manufacturer.strip(),
                        "mpn": identity.mpn.strip(),
                        "package": identity.package.strip(),
                    },
                    "identity_verification": {
                        "method": "exact_text_orderable_part",
                        "policy_version": IDENTITY_POLICY_VERSION,
                        "outcome": "accepted",
                        "manufacturer_observed": True,
                        "exact_mpn_observed": True,
                        "package_associated": True,
                        "evidence_region_ids": ["r_package_01"],
                    },
                    "regions": regions,
                    "retrieval": {
                        "index_version": INDEX_VERSION,
                        "model_ids": MODEL_IDS,
                        "query_ids": ["q_pinout", "q_pin_table", "q_exact_identity_package"],
                    },
                }
                (staging / "evidence.json").write_text(
                    json.dumps(bundle, indent=2) + "\n", encoding="utf-8"
                )
                if pack_dir.exists():
                    corrupt = output_root / f".{pack_id}.corrupt"
                    if corrupt.exists():
                        shutil.rmtree(corrupt)
                    os.replace(pack_dir, corrupt)
                    shutil.rmtree(corrupt)
                os.replace(staging, pack_dir)
                return bundle
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
    except FileLockTimeout as exc:
        raise RetrievalError("evidence pack is busy; retry the request") from exc

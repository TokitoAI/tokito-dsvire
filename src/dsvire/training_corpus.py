"""Provenance-controlled training corpus admission. Vendor PDF bytes stay off Git."""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pypdf import PdfReader

from .eval_download import EvaluationDownloadError, fetch_hash_pinned_file
from .pipeline import MAX_PDF_BYTES
from .sealed_holdout import SealedHoldout, leakage_hits, load_sealed_holdout, normalize_url

CORPUS_VERSION = "dsvire.training-corpus.v1"
CONTRIBUTION_VERSION = "dsvire.corpus-contribution.v1"
CATEGORIES = frozenset(
    {
        "analog_mixed_signal",
        "connector",
        "discrete",
        "interface_logic",
        "memory",
        "microcontroller_fpga",
        "other",
        "power_management",
        "rf",
        "sensor",
    }
)
LABEL_TIERS = frozenset({"catalog_identity_supported", "layout_only_weak_identity"})
QUARANTINE_REASONS = frozenset(
    {
        "network",
        "redirect_off_allowlist",
        "invalid_magic",
        "encrypted",
        "parse_failure",
        "bounds",
        "duplicate",
        "sealed_overlap",
        "identity_ambiguous",
        "non_datasheet",
        "terms_unreviewed",
        "third_party_dataset_unreviewed",
    }
)
OFFICIAL_HOST_SUFFIXES = (
    "ti.com",
    "nxp.com",
    "microchip.com",
    "infineon.com",
    "onsemi.com",
    "diodes.com",
    "nexperia.com",
    "vishay.com",
    "rohm.com",
    "silabs.com",
    "skyworksinc.com",
    "broadcom.com",
    "allegromicro.com",
    "bourns.com",
    "macom.com",
    "meanwell.com",
    "tracopower.com",
    "traco-power.com",
    "we-online.com",
    "issi.com",
    "winbond.com",
    "ams-osram.com",
    "abracon.com",
    "analog.com",
    "st.com",
    "renesas.com",
    "qorvo.com",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[a-z0-9]+")


class TrainingCorpusError(ValueError):
    """A training corpus record violated provenance, leakage, or split policy."""


@dataclass(frozen=True)
class CorpusRecord:
    content_sha256: str
    bytes: int
    page_count: int
    source_url: str
    final_url: str
    retrieved_at: str
    manufacturer: str
    category: str
    symbols: tuple[str, ...]
    label_tier: str
    permitted_use: str
    terms_url: str
    split: Literal["training_candidate"]


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrainingCorpusError(f"{context} must be non-empty text")
    if "\x00" in value:
        raise TrainingCorpusError(f"{context} contains NUL")
    return value.strip()


def _sha(value: Any, context: str) -> str:
    digest = _text(value, context).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise TrainingCorpusError(f"{context} must be lowercase SHA-256")
    return digest


def official_host(url: str) -> bool:
    host = urlparse(normalize_url(url)).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES)


def cache_path(cache_root: Path, content_sha256: str) -> Path:
    digest = _sha(content_sha256, "content_sha256")
    return cache_root / "raw" / digest[:2] / f"{digest}.pdf"


def parse_corpus_record(value: Any) -> CorpusRecord:
    if not isinstance(value, Mapping):
        raise TrainingCorpusError("corpus record must be an object")
    split = _text(value.get("split", "training_candidate"), "split")
    if split != "training_candidate":
        raise TrainingCorpusError(
            "vendor corpus records cannot claim a development or evaluation split"
        )
    category = _text(value.get("category"), "category")
    if category not in CATEGORIES:
        raise TrainingCorpusError(f"unsupported category: {category}")
    tier = _text(value.get("label_tier"), "label_tier")
    if tier not in LABEL_TIERS:
        raise TrainingCorpusError(f"unsupported label_tier: {tier}")
    symbols_raw = value.get("symbols")
    if not isinstance(symbols_raw, list) or not symbols_raw:
        raise TrainingCorpusError("symbols must be a non-empty array")
    symbols = tuple(_text(item, "symbols") for item in symbols_raw)
    if len(set(item.casefold() for item in symbols)) != len(symbols):
        raise TrainingCorpusError("symbols contain duplicates")
    source_url = normalize_url(
        _text(value.get("source_url") or value.get("requested_url"), "source_url")
    )
    final_url = normalize_url(_text(value.get("final_url"), "final_url"))
    if not official_host(source_url) or not official_host(final_url):
        raise TrainingCorpusError("training sources must be official manufacturer HTTPS hosts")
    bytes_count = value.get("bytes")
    pages = value.get("page_count")
    if not isinstance(bytes_count, int) or isinstance(bytes_count, bool) or bytes_count < 8:
        raise TrainingCorpusError("bytes must be an integer >= 8")
    if bytes_count > MAX_PDF_BYTES:
        raise TrainingCorpusError("bytes exceed the production PDF cap")
    if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
        raise TrainingCorpusError("page_count must be a positive integer")
    retrieved = _text(value.get("retrieved_at"), "retrieved_at")
    datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
    return CorpusRecord(
        content_sha256=_sha(value.get("content_sha256"), "content_sha256"),
        bytes=bytes_count,
        page_count=pages,
        source_url=source_url,
        final_url=final_url,
        retrieved_at=retrieved,
        manufacturer=_text(value.get("manufacturer"), "manufacturer"),
        category=category,
        symbols=symbols,
        label_tier=tier,
        permitted_use=_text(value.get("permitted_use"), "permitted_use"),
        terms_url=_text(value.get("terms_url"), "terms_url"),
        split="training_candidate",
    )


def load_corpus_jsonl(path: Path) -> tuple[CorpusRecord, ...]:
    records: list[CorpusRecord] = []
    seen: set[str] = set()
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        record = parse_corpus_record(json.loads(line))
        if record.content_sha256 in seen:
            raise TrainingCorpusError(f"duplicate corpus digest at line {index + 1}")
        seen.add(record.content_sha256)
        records.append(record)
    if not records:
        raise TrainingCorpusError("corpus.jsonl is empty")
    return tuple(records)


def audit_corpus(
    records: Sequence[CorpusRecord],
    *,
    holdout: SealedHoldout | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    sealed = holdout or load_sealed_holdout(root or Path(__file__).resolve().parents[2])
    overlaps: list[dict[str, str]] = []
    manufacturers: set[str] = set()
    categories: set[str] = set()
    for record in records:
        hits = leakage_hits(
            sealed,
            url=record.final_url,
            content_sha256=record.content_sha256,
            identity_text=(record.manufacturer, *record.symbols),
        )
        extra = leakage_hits(sealed, url=record.source_url)
        found = tuple(dict.fromkeys((*hits, *extra)))
        if found:
            overlaps.append({"content_sha256": record.content_sha256, "hits": ",".join(found)})
        manufacturers.add(record.manufacturer)
        categories.add(record.category)
    if overlaps:
        raise TrainingCorpusError(
            "corpus leaks into sealed evaluation material: "
            + "; ".join(item["content_sha256"][:12] for item in overlaps)
        )
    if len(categories) < 8:
        raise TrainingCorpusError("corpus is not stratified across the required category set")
    return {
        "schema_version": CORPUS_VERSION,
        "documents": len(records),
        "manufacturers": len(manufacturers),
        "categories": sorted(categories),
        "sealed_url_overlap": 0,
        "sealed_hash_overlap": 0,
        "sealed_family_marker_overlap": 0,
        "split_policy": "training_candidate_only; family clusters required before any development split",
    }


def refuse_hash_split(records: Sequence[CorpusRecord]) -> None:
    """Content-hash partitions are forbidden because they leak near-family documents."""
    del records
    raise TrainingCorpusError(
        "do not create train/development splits by document hash; assign reviewed family clusters"
    )


def fingerprint_pdf(payload: bytes) -> dict[str, str | int | float]:
    if not payload.startswith(b"%PDF-"):
        raise TrainingCorpusError("payload is not a PDF")
    digest = hashlib.sha256(payload).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if getattr(reader, "is_encrypted", False):
            raise TrainingCorpusError("encrypted PDFs are quarantined")
        pages = len(reader.pages)
        text_parts: list[str] = []
        for page in reader.pages[:32]:
            extracted = page.extract_text() or ""
            text_parts.append(extracted)
        text = "\n".join(text_parts)
    except TrainingCorpusError:
        raise
    except Exception as exc:
        raise TrainingCorpusError("PDF structural parse failed") from exc
    if pages < 1:
        raise TrainingCorpusError("PDF contains no pages")
    normalized = "".join(_TOKEN.findall(text.casefold()))
    coverage = min(1.0, len(normalized) / max(pages * 80, 1))
    return {
        "content_sha256": digest,
        "page_count": pages,
        "bytes": len(payload),
        "normalized_text_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "text_coverage": round(coverage, 6),
        "head_sha256": hashlib.sha256(normalized[:2048].encode()).hexdigest(),
        "tail_sha256": hashlib.sha256(normalized[-2048:].encode()).hexdigest(),
    }


def admit_pdf(
    payload: bytes,
    *,
    record: CorpusRecord,
    holdout: SealedHoldout,
) -> dict[str, Any]:
    if len(payload) != record.bytes:
        raise TrainingCorpusError("byte count does not match the corpus record")
    fingerprint = fingerprint_pdf(payload)
    if fingerprint["content_sha256"] != record.content_sha256:
        raise TrainingCorpusError("PDF digest does not match the corpus record")
    if int(fingerprint["page_count"]) != record.page_count:
        raise TrainingCorpusError("page count does not match the corpus record")
    hits = leakage_hits(
        holdout,
        url=record.final_url,
        content_sha256=record.content_sha256,
        identity_text=(record.manufacturer, *record.symbols),
    )
    if hits:
        raise TrainingCorpusError(f"record is sealed evaluation material: {','.join(hits)}")
    return fingerprint


def materialize_record(
    record: CorpusRecord,
    *,
    cache_root: Path,
    holdout: SealedHoldout,
    offline: bool = False,
) -> Path:
    path = cache_path(cache_root, record.content_sha256)
    try:
        fetched = fetch_hash_pinned_file(
            artifact_id=record.content_sha256,
            source_url=record.final_url,
            content_sha256=record.content_sha256,
            expected_bytes=record.bytes,
            max_bytes=MAX_PDF_BYTES,
            cache_dir=path.parent,
            suffix=".pdf",
            offline=offline,
            allow_final_url=official_host,
        )
    except EvaluationDownloadError as exc:
        raise TrainingCorpusError(str(exc)) from exc
    if fetched.resolve() != path.resolve():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(fetched.read_bytes())
    payload = path.read_bytes()
    admit_pdf(payload, record=record, holdout=holdout)
    return path


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

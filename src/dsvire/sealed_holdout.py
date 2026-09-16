"""Exact sealed evaluation identities that training and corpus acquisition must exclude."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .visual_registry import load_visual_registry_data

_TOKEN = re.compile(r"[a-z0-9]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
ROOT = Path(__file__).resolve().parents[2]


class SealedHoldoutError(ValueError):
    """Sealed evaluation material could not be loaded without leakage risk."""


@dataclass(frozen=True)
class SealedHoldout:
    urls: frozenset[str]
    hosts: frozenset[str]
    content_sha256: frozenset[str]
    family_ids: frozenset[str]
    family_markers: frozenset[str]
    plan_ids: frozenset[str]


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SealedHoldoutError(f"{context} must be non-empty text")
    return value.strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(_text(url, "url"))
    if parsed.scheme != "https" or not parsed.netloc:
        raise SealedHoldoutError("sealed source URL must be HTTPS with a host")
    path = parsed.path.rstrip("/")
    return f"https://{parsed.netloc.lower()}{path}"


def family_markers(*values: str) -> frozenset[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(
            token
            for token in _TOKEN.findall(value.casefold())
            if len(token) >= 6
            and token
            not in {"datasheet", "revision", "selected", "calibration", "evaluation", "https"}
        )
    return frozenset(tokens)


def load_sealed_holdout(root: Path = ROOT) -> SealedHoldout:
    urls: set[str] = set()
    hashes: set[str] = set()
    family_ids: set[str] = set()
    markers: set[str] = set()
    plan_ids: set[str] = set()
    evaluation = root / "evaluation"
    if not evaluation.is_dir():
        raise SealedHoldoutError("evaluation directory is missing")
    for path in sorted(evaluation.glob("retrieval_cycle_v*_preregistration.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(plan, Mapping):
            raise SealedHoldoutError(f"{path.name} is not an object")
        plan_ids.add(_text(plan.get("plan_id"), f"{path.name}.plan_id"))
        families = plan.get("families")
        if not isinstance(families, list) or not families:
            raise SealedHoldoutError(f"{path.name} has no families")
        for family in families:
            if not isinstance(family, Mapping):
                raise SealedHoldoutError(f"{path.name} contains a non-object family")
            family_id = _text(family.get("id"), "family.id")
            family_ids.add(family_id)
            urls.add(normalize_url(_text(family.get("official_source_url"), "official_source_url")))
            markers.update(
                family_markers(
                    family_id,
                    _text(family.get("datasheet_identity"), "datasheet_identity"),
                    _text(family.get("selected_mpn"), "selected_mpn"),
                )
            )
    for path in sorted(evaluation.glob("retrieval_cycle_v*_source_manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        sources = manifest.get("sources") if isinstance(manifest, Mapping) else None
        if not isinstance(sources, list):
            raise SealedHoldoutError(f"{path.name} has no sources")
        for source in sources:
            if not isinstance(source, Mapping):
                raise SealedHoldoutError(f"{path.name} contains a non-object source")
            digest = _text(source.get("content_sha256"), "content_sha256")
            if _SHA256.fullmatch(digest) is None:
                raise SealedHoldoutError(f"{path.name} has a non-SHA-256 content digest")
            hashes.add(digest)
            urls.add(normalize_url(_text(source.get("final_url"), "final_url")))
            urls.add(normalize_url(_text(source.get("requested_url"), "requested_url")))
    registry_path = evaluation / "visual_registry.v1.json"
    registry = load_visual_registry_data(json.loads(registry_path.read_text(encoding="utf-8")))
    for document in registry.documents:
        family_ids.add(document.document_id)
        family_ids.add(document.document_group)
        hashes.add(document.content_sha256)
        urls.add(normalize_url(document.source.url))
        markers.update(
            family_markers(
                document.document_id,
                document.document_group,
                document.identity.mpn,
            )
        )
    hosts = {urlparse(url).netloc.lower() for url in urls}
    return SealedHoldout(
        urls=frozenset(urls),
        hosts=frozenset(hosts),
        content_sha256=frozenset(hashes),
        family_ids=frozenset(family_ids),
        family_markers=frozenset(markers),
        plan_ids=frozenset(plan_ids),
    )


def leakage_hits(
    holdout: SealedHoldout,
    *,
    url: str | None = None,
    content_sha256: str | None = None,
    family_id: str | None = None,
    identity_text: Iterable[str] = (),
) -> tuple[str, ...]:
    hits: list[str] = []
    if url is not None:
        normalized = normalize_url(url)
        if normalized in holdout.urls:
            hits.append("sealed_url")
    if content_sha256 is not None:
        digest = content_sha256.strip().casefold()
        if _SHA256.fullmatch(digest) is None:
            raise SealedHoldoutError("content_sha256 must be lowercase SHA-256")
        if digest in holdout.content_sha256:
            hits.append("sealed_hash")
    if family_id is not None and family_id.strip() in holdout.family_ids:
        hits.append("sealed_family_id")
    observed = family_markers(*identity_text, *(family_id,) if family_id else ())
    if observed & holdout.family_markers:
        hits.append("sealed_family_marker")
    return tuple(hits)

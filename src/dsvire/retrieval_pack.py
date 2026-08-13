"""Strict, content-addressed packs for the online hybrid retrieval path."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PACK_VERSION = "dsvire.retrieval-pack.v1"
ALLOWED_REGION_TYPES = {"pinout", "table", "package"}
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_REGIONS = 100_000
MAX_TEXT_BYTES = 64_000
MAX_VECTOR_DIM = 8_192
MAX_PATCHES = 4_096
MAX_TOTAL_VECTOR_VALUES = 50_000_000
VECTOR_DTYPE = "float32"


class RetrievalPackError(ValueError):
    """A pack is corrupt, incompatible, or outside its resource contract."""


@dataclass(frozen=True)
class ModelIdentity:
    id: str
    sha256: str


@dataclass(frozen=True)
class Region:
    id: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    region_type: str
    content_sha256: str
    text_fields: tuple[tuple[str, str], ...]
    dense: tuple[float, ...]
    multi: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class RetrievalPack:
    pack_sha256: str
    source_sha256: str
    dense_model: ModelIdentity
    multi_model: ModelIdentity
    dense_dim: int
    multi_dim: int
    vector_dtype: str
    regions: tuple[Region, ...]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _text(value: Any, context: str, *, max_bytes: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalPackError(f"{context} must be non-empty text")
    result = value.strip()
    if len(result.encode()) > max_bytes or "\x00" in result:
        raise RetrievalPackError(f"{context} is outside its text limit")
    return result


def _sha(value: Any, context: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise RetrievalPackError(f"{context} must be lowercase SHA-256")
    return value


def _model(value: Any, context: str) -> ModelIdentity:
    if not isinstance(value, Mapping) or set(value) != {"id", "sha256"}:
        raise RetrievalPackError(f"{context} must contain only id and sha256")
    return ModelIdentity(
        _text(value["id"], f"{context}.id"), _sha(value["sha256"], f"{context}.sha256")
    )


def _vector(value: Any, dimension: int, context: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != dimension:
        raise RetrievalPackError(f"{context} must have dimension {dimension}")
    result: list[float] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise RetrievalPackError(f"{context} must contain only numbers")
        number = float(raw)
        if not math.isfinite(number) or abs(number) > 1_000_000:
            raise RetrievalPackError(f"{context} contains an invalid value")
        result.append(number)
    return tuple(result)


def load_retrieval_pack(
    value: Any,
    *,
    expected_dense_model: ModelIdentity | None = None,
    expected_multi_model: ModelIdentity | None = None,
) -> RetrievalPack:
    """Validate an untrusted JSON-decoded pack and bind its canonical payload."""
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "payload_sha256",
        "payload",
    }:
        raise RetrievalPackError("pack envelope keys are invalid")
    if value["schema_version"] != PACK_VERSION:
        raise RetrievalPackError("unsupported retrieval pack version")
    expected = _sha(value["payload_sha256"], "payload_sha256")
    payload = value["payload"]
    if hashlib.sha256(_canonical(payload)).hexdigest() != expected:
        raise RetrievalPackError("retrieval pack payload digest mismatch")
    if not isinstance(payload, Mapping) or set(payload) != {
        "source_sha256",
        "models",
        "dense_dim",
        "multi_dim",
        "vector_dtype",
        "regions",
    }:
        raise RetrievalPackError("retrieval pack payload keys are invalid")
    models = payload["models"]
    if not isinstance(models, Mapping) or set(models) != {"dense", "multi"}:
        raise RetrievalPackError("models must contain only dense and multi")
    dense_model = _model(models["dense"], "models.dense")
    multi_model = _model(models["multi"], "models.multi")
    if expected_dense_model is not None and dense_model != expected_dense_model:
        raise RetrievalPackError("dense model identity mismatch")
    if expected_multi_model is not None and multi_model != expected_multi_model:
        raise RetrievalPackError("multi model identity mismatch")
    if payload["vector_dtype"] != VECTOR_DTYPE:
        raise RetrievalPackError(f"vector_dtype must be {VECTOR_DTYPE}")
    dense_dim, multi_dim = payload["dense_dim"], payload["multi_dim"]
    if (
        isinstance(dense_dim, bool)
        or not isinstance(dense_dim, int)
        or isinstance(multi_dim, bool)
        or not isinstance(multi_dim, int)
        or not 1 <= dense_dim <= MAX_VECTOR_DIM
        or not 1 <= multi_dim <= MAX_VECTOR_DIM
    ):
        raise RetrievalPackError("vector dimensions are outside the supported range")
    raw_regions = payload["regions"]
    if not isinstance(raw_regions, list) or not 1 <= len(raw_regions) <= MAX_REGIONS:
        raise RetrievalPackError("regions are outside the supported count")
    regions: list[Region] = []
    seen: set[str] = set()
    total_vector_values = 0
    for index, raw in enumerate(raw_regions):
        context = f"regions[{index}]"
        required = {
            "id",
            "page",
            "bbox_norm",
            "type",
            "content_sha256",
            "text_fields",
            "dense",
            "multi",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise RetrievalPackError(f"{context} keys are invalid")
        region_id = _text(raw["id"], f"{context}.id", max_bytes=1024)
        if (
            region_id in seen
            or region_id.startswith(("/", "\\"))
            or ".." in region_id.replace("\\", "/").split("/")
        ):
            raise RetrievalPackError(f"{context}.id is duplicate or unsafe")
        seen.add(region_id)
        page = raw["page"]
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 100_000:
            raise RetrievalPackError(f"{context}.page is invalid")
        bbox = raw["bbox_norm"]
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise RetrievalPackError(f"{context}.bbox_norm is invalid")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in bbox):
            raise RetrievalPackError(f"{context}.bbox_norm is invalid")
        coords = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        if not all(math.isfinite(item) for item in coords) or not (
            0 <= coords[0] < coords[2] <= 1 and 0 <= coords[1] < coords[3] <= 1
        ):
            raise RetrievalPackError(f"{context}.bbox_norm is invalid")
        region_type = _text(raw["type"], f"{context}.type")
        if region_type not in ALLOWED_REGION_TYPES:
            raise RetrievalPackError(f"{context}.type is unsupported")
        text_fields = raw["text_fields"]
        allowed_fields = {"caption", "pins", "section", "crop"}
        if not isinstance(text_fields, Mapping) or not set(text_fields) <= allowed_fields:
            raise RetrievalPackError(f"{context}.text_fields keys are invalid")
        parsed_fields: list[tuple[str, str]] = []
        text_bytes = 0
        for name in sorted(text_fields):
            field = text_fields[name]
            if not isinstance(field, str) or "\x00" in field:
                raise RetrievalPackError(f"{context}.text_fields.{name} is invalid")
            text_bytes += len(field.encode())
            parsed_fields.append((name, field))
        if text_bytes > MAX_TEXT_BYTES:
            raise RetrievalPackError(f"{context}.text_fields exceed their byte limit")
        raw_multi = raw["multi"]
        if not isinstance(raw_multi, list) or not 1 <= len(raw_multi) <= MAX_PATCHES:
            raise RetrievalPackError(f"{context}.multi is outside its patch limit")
        total_vector_values += dense_dim + len(raw_multi) * multi_dim
        if total_vector_values > MAX_TOTAL_VECTOR_VALUES:
            raise RetrievalPackError("retrieval pack exceeds its aggregate vector limit")
        regions.append(
            Region(
                region_id,
                page,
                coords,
                region_type,
                _sha(raw["content_sha256"], f"{context}.content_sha256"),
                tuple(parsed_fields),
                _vector(raw["dense"], dense_dim, f"{context}.dense"),
                tuple(_vector(item, multi_dim, f"{context}.multi") for item in raw_multi),
            )
        )
    if [region.id for region in regions] != sorted(seen):
        raise RetrievalPackError("regions must be sorted by id")
    return RetrievalPack(
        expected,
        _sha(payload["source_sha256"], "source_sha256"),
        dense_model,
        multi_model,
        dense_dim,
        multi_dim,
        VECTOR_DTYPE,
        tuple(regions),
    )


def build_retrieval_pack(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build then re-validate a canonical envelope; callers provide real encoder output."""
    frozen_payload: Any = json.loads(_canonical(payload))
    envelope = {
        "schema_version": PACK_VERSION,
        "payload_sha256": hashlib.sha256(_canonical(frozen_payload)).hexdigest(),
        "payload": frozen_payload,
    }
    load_retrieval_pack(envelope)
    return envelope

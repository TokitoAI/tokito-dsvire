"""Frozen split-plan identity and registry conformance checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .visual_registry import VisualRegistry


def load_visual_split_plan_data(value: Any) -> tuple[dict[str, Mapping[str, Any]], str]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "dsvire.visual-split-plan.v1"
    ):
        raise ValueError("unsupported visual split plan")
    families = value.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("visual split plan has no families")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, family in enumerate(families):
        if not isinstance(family, Mapping):
            raise ValueError(f"visual split plan family {index} is invalid")
        family_id = family.get("id")
        if not isinstance(family_id, str) or not family_id or family_id in by_id:
            raise ValueError(f"visual split plan family {index} has an invalid or duplicate id")
        by_id[family_id] = family
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return by_id, digest


def bind_registry_to_split_plan(
    registry: VisualRegistry, plan: Mapping[str, Mapping[str, Any]], split: str
) -> None:
    planned = {
        family_id: family for family_id, family in plan.items() if family.get("split") == split
    }
    observed = {document.document_id: document for document in registry.documents}
    if set(observed) != set(planned):
        raise ValueError(
            f"{split} registry does not exactly match frozen split plan: "
            f"missing={sorted(set(planned) - set(observed))}, "
            f"unknown={sorted(set(observed) - set(planned))}"
        )
    for document_id, document in observed.items():
        family = planned[document_id]
        if (
            family.get("content_sha256") != document.content_sha256
            or family.get("category") != document.category
            or family.get("source_url") != document.source.url
        ):
            raise ValueError(f"{document_id}: registry drifted from frozen split plan")

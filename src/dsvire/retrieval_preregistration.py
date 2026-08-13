"""Fail-closed validation for retrieval benchmark pre-registrations."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

VERSION = "dsvire.retrieval-preregistration.v1"
SPLITS = {"calibration", "evaluation"}
REQUIRED_MANUFACTURERS = {
    "Texas Instruments": "www.ti.com",
    "Analog Devices": "www.analog.com",
    "Nexperia": "assets.nexperia.com",
    "Microchip": "ww1.microchip.com",
    "STMicroelectronics": "www.st.com",
    "onsemi": "www.onsemi.com",
    "NXP Semiconductors": "www.nxp.com",
    "Bosch Sensortec": "www.bosch-sensortec.com",
}


class RetrievalPreregistrationError(ValueError):
    """A pre-registration is mutable, overlapping, or structurally incomplete."""


@dataclass(frozen=True)
class RetrievalPreregistration:
    plan_id: str
    content_sha256: str
    family_ids: tuple[str, ...]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_retrieval_preregistration(
    value: Any, *, consumed_family_ids: set[str]
) -> RetrievalPreregistration:
    if not isinstance(value, Mapping) or value.get("schema_version") != VERSION:
        raise RetrievalPreregistrationError("unsupported retrieval pre-registration")
    required = {
        "schema_version",
        "plan_id",
        "parent_issue",
        "tracking_issue",
        "sealed_before",
        "families",
        "acquisition",
        "annotation",
        "queries",
        "candidate_universe",
        "systems",
        "metrics",
        "frozen_gate",
        "execution_order",
        "invalidation",
        "publication_policy",
    }
    if set(value) != required:
        raise RetrievalPreregistrationError("pre-registration keys are invalid")
    plan_id = value["plan_id"]
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise RetrievalPreregistrationError("plan_id is invalid")
    families = value["families"]
    if not isinstance(families, list) or len(families) != 12:
        raise RetrievalPreregistrationError("exactly twelve families are required")
    expected_keys = {
        "id",
        "split",
        "manufacturer",
        "category",
        "datasheet_identity",
        "selected_mpn",
        "selected_package",
        "official_source_url",
    }
    ids: list[str] = []
    splits: Counter[str] = Counter()
    manufacturers: dict[str, set[str]] = {split: set() for split in SPLITS}
    categories: set[str] = set()
    for index, family in enumerate(families):
        if not isinstance(family, Mapping) or set(family) != expected_keys:
            raise RetrievalPreregistrationError(f"families[{index}] keys are invalid")
        if any(
            not isinstance(family[key], str) or not family[key].strip() for key in expected_keys
        ):
            raise RetrievalPreregistrationError(f"families[{index}] contains empty text")
        family_id, split = family["id"], family["split"]
        if split not in SPLITS:
            raise RetrievalPreregistrationError(f"families[{index}].split is invalid")
        host = urlparse(family["official_source_url"])
        expected_host = REQUIRED_MANUFACTURERS.get(family["manufacturer"])
        if host.scheme != "https" or host.hostname != expected_host or host.username is not None:
            raise RetrievalPreregistrationError(f"families[{index}] source is not official HTTPS")
        ids.append(family_id)
        splits[split] += 1
        manufacturers[split].add(family["manufacturer"])
        if family["category"] in categories:
            raise RetrievalPreregistrationError("categories must be unique across the cycle")
        categories.add(family["category"])
    if len(set(ids)) != len(ids) or set(ids) & consumed_family_ids:
        raise RetrievalPreregistrationError("family IDs are duplicate or previously consumed")
    if splits != Counter({"calibration": 6, "evaluation": 6}):
        raise RetrievalPreregistrationError("splits must contain six families each")
    if (
        not manufacturers["calibration"]
        or manufacturers["calibration"] != manufacturers["evaluation"]
    ):
        raise RetrievalPreregistrationError("manufacturer strata must match across splits")
    gate = value["frozen_gate"]
    expected_gate = {
        "evaluation_queries_minimum": 36,
        "coverage_minimum": 1.0,
        "crop_recall_at_5_vs_full_page_minimum_delta": -0.01,
        "crop_recall_at_5_vs_openclip_minimum_delta": 0.15,
        "crop_recall_at_5_vs_text_rag_minimum_delta": 0.15,
        "verified_wrong_figure_rate_maximum": 0.02,
        "target_gpu_hot_query_p95_ms_maximum": 800,
        "crop_index_pages_per_second_per_gpu_minimum": 2.0,
        "compressed_crop_pack_vs_full_page_ratio_maximum": 0.15,
        "all_conditions_required": True,
    }
    if gate != expected_gate:
        raise RetrievalPreregistrationError("frozen gate differs from the registered target")
    if (
        value["publication_policy"].startswith("automated catalog publication remains disabled")
        is False
    ):
        raise RetrievalPreregistrationError("publication policy must remain fail-closed")
    return RetrievalPreregistration(
        plan_id.strip(), hashlib.sha256(_canonical(value)).hexdigest(), tuple(ids)
    )

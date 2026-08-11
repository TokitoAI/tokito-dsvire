"""Strict provenance and annotation contract for the EGVV benchmark."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from .visual_metrics import (
    ALLOWED_LABELS,
    ALLOWED_SPLITS,
    POSITIVE,
    WRONG_IDENTITY,
    Prediction,
    VisualMetricError,
)

REGISTRY_VERSION = "dsvire.visual-eval-registry.v1"
ALLOWED_REDISTRIBUTION = {"download_only", "redistributable"}
ALLOWED_REGION_TYPES = {"pinout", "table", "package"}
ALLOWED_VIEWS = {"top", "bottom", "not_applicable", "unknown"}
REQUIRED_POSITIVE_REGIONS = ALLOWED_REGION_TYPES
SHA256 = re.compile(r"[0-9a-f]{64}")


class VisualRegistryError(ValueError):
    """The visual evaluation registry violates its frozen contract."""


def _strict(value: Mapping[str, Any], required: set[str], context: str) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing or unknown:
        raise VisualRegistryError(
            f"{context} keys invalid: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualRegistryError(f"{context} must be non-empty text")
    return value.strip()


@dataclasses.dataclass(frozen=True)
class Identity:
    manufacturer: str
    mpn: str
    package: str

    @classmethod
    def parse(cls, value: Any, context: str) -> Identity:
        if not isinstance(value, Mapping):
            raise VisualRegistryError(f"{context} must be an object")
        _strict(value, {"manufacturer", "mpn", "package"}, context)
        return cls(
            _text(value["manufacturer"], f"{context}.manufacturer"),
            _text(value["mpn"], f"{context}.mpn"),
            _text(value["package"], f"{context}.package"),
        )


@dataclasses.dataclass(frozen=True)
class Source:
    url: str
    revision: str

    @classmethod
    def parse(cls, value: Any, context: str) -> Source:
        if not isinstance(value, Mapping):
            raise VisualRegistryError(f"{context} must be an object")
        _strict(value, {"url", "revision"}, context)
        url = _text(value["url"], f"{context}.url")
        if not url.startswith("https://"):
            raise VisualRegistryError(f"{context}.url must use HTTPS")
        return cls(url, _text(value["revision"], f"{context}.revision"))


@dataclasses.dataclass(frozen=True)
class Review:
    status: str
    reviewers: tuple[str, ...]
    reviewed_at: str | None
    annotation_revision: str

    @classmethod
    def parse(cls, value: Any, context: str) -> Review:
        if not isinstance(value, Mapping):
            raise VisualRegistryError(f"{context} must be an object")
        _strict(
            value,
            {"status", "reviewers", "reviewed_at", "annotation_revision"},
            context,
        )
        status = _text(value["status"], f"{context}.status")
        if status not in {"unreviewed", "reviewed"}:
            raise VisualRegistryError(f"{context}.status must be unreviewed or reviewed")
        reviewers_raw = value["reviewers"]
        if not isinstance(reviewers_raw, list):
            raise VisualRegistryError(f"{context}.reviewers must be an array")
        reviewers = tuple(
            _text(reviewer, f"{context}.reviewers[{index}]")
            for index, reviewer in enumerate(reviewers_raw)
        )
        if len(reviewers) != len(set(reviewers)):
            raise VisualRegistryError(f"{context}.reviewers contains duplicates")
        reviewed_at = value["reviewed_at"]
        if reviewed_at is not None:
            reviewed_at = _text(reviewed_at, f"{context}.reviewed_at")
            try:
                parsed = dt.datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise VisualRegistryError(f"{context}.reviewed_at must be ISO-8601") from exc
            if parsed.tzinfo is None:
                raise VisualRegistryError(f"{context}.reviewed_at must include a timezone")
        if status == "reviewed" and (not reviewers or reviewed_at is None):
            raise VisualRegistryError(
                f"{context} reviewed annotations require reviewers and reviewed_at"
            )
        if status == "unreviewed" and (reviewers or reviewed_at is not None):
            raise VisualRegistryError(
                f"{context} unreviewed annotations cannot claim reviewers or reviewed_at"
            )
        return cls(
            status,
            reviewers,
            reviewed_at,
            _text(value["annotation_revision"], f"{context}.annotation_revision"),
        )


def _bbox(value: Any, context: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise VisualRegistryError(f"{context} must contain four normalized coordinates")
    coordinates: list[float] = []
    for index, coordinate in enumerate(value):
        if (
            not isinstance(coordinate, (int, float))
            or isinstance(coordinate, bool)
            or not math.isfinite(coordinate)
            or not 0 <= coordinate <= 1
        ):
            raise VisualRegistryError(f"{context}[{index}] must be finite within 0..=1")
        coordinates.append(float(coordinate))
    x0, y0, x1, y1 = coordinates
    if x0 >= x1 or y0 >= y1:
        raise VisualRegistryError(f"{context} must have positive width and height")
    return x0, y0, x1, y1


@dataclasses.dataclass(frozen=True)
class VisualCase:
    case_id: str
    label: str
    region_type: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    view: str
    claimed_identity: Identity
    rationale: str

    @classmethod
    def parse(cls, value: Any, context: str) -> VisualCase:
        if not isinstance(value, Mapping):
            raise VisualRegistryError(f"{context} must be an object")
        _strict(
            value,
            {
                "id",
                "label",
                "region_type",
                "page",
                "bbox_norm",
                "view",
                "claimed_identity",
                "rationale",
            },
            context,
        )
        label = _text(value["label"], f"{context}.label")
        if label not in ALLOWED_LABELS:
            raise VisualRegistryError(f"{context}.label is unsupported: {label!r}")
        region_type = _text(value["region_type"], f"{context}.region_type")
        if region_type not in ALLOWED_REGION_TYPES:
            raise VisualRegistryError(f"{context}.region_type is unsupported: {region_type!r}")
        page = value["page"]
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise VisualRegistryError(f"{context}.page must be a positive integer")
        view = _text(value["view"], f"{context}.view")
        if view not in ALLOWED_VIEWS:
            raise VisualRegistryError(f"{context}.view is unsupported: {view!r}")
        return cls(
            _text(value["id"], f"{context}.id"),
            label,
            region_type,
            page,
            _bbox(value["bbox_norm"], f"{context}.bbox_norm"),
            view,
            Identity.parse(value["claimed_identity"], f"{context}.claimed_identity"),
            _text(value["rationale"], f"{context}.rationale"),
        )


@dataclasses.dataclass(frozen=True)
class VisualDocument:
    document_id: str
    document_group: str
    split: str
    category: str
    source: Source
    content_sha256: str
    redistribution: str
    license_note: str
    identity: Identity
    review: Review
    cases: tuple[VisualCase, ...]


@dataclasses.dataclass(frozen=True)
class VisualRegistry:
    documents: tuple[VisualDocument, ...]
    content_sha256: str


def _validate_identity_relationship(case: VisualCase, identity: Identity, context: str) -> None:
    claimed = case.claimed_identity
    if case.label == POSITIVE and claimed != identity:
        raise VisualRegistryError(f"{context} positive case must claim the document identity")
    if case.label == "wrong_package" and not (
        claimed.manufacturer == identity.manufacturer
        and claimed.mpn == identity.mpn
        and claimed.package != identity.package
    ):
        raise VisualRegistryError(f"{context} wrong_package must differ only by package")
    if case.label == "wrong_variant" and not (
        claimed.manufacturer == identity.manufacturer
        and claimed.mpn != identity.mpn
        and claimed.package == identity.package
    ):
        raise VisualRegistryError(f"{context} wrong_variant must differ only by MPN")
    if case.label in {"wrong_figure", "wrong_view"} and claimed != identity:
        raise VisualRegistryError(f"{context} visual negative must retain the document identity")
    if case.label in WRONG_IDENTITY and case.region_type != "package":
        raise VisualRegistryError(f"{context} identity negative must use a package region")


def load_visual_registry_data(value: Any) -> VisualRegistry:
    if not isinstance(value, Mapping):
        raise VisualRegistryError("registry must be an object")
    _strict(value, {"schema_version", "documents"}, "registry")
    if value["schema_version"] != REGISTRY_VERSION:
        raise VisualRegistryError(f"unsupported registry version: {value['schema_version']!r}")
    documents_raw = value["documents"]
    if not isinstance(documents_raw, list) or not documents_raw:
        raise VisualRegistryError("registry.documents must be a non-empty array")

    documents: list[VisualDocument] = []
    ids: set[str] = set()
    case_ids: set[str] = set()
    group_splits: dict[str, str] = {}
    hash_owners: dict[str, tuple[str, str]] = {}
    required = {
        "id",
        "document_group",
        "split",
        "category",
        "source",
        "content_sha256",
        "redistribution",
        "license_note",
        "identity",
        "review",
        "cases",
    }
    for index, raw in enumerate(documents_raw):
        context = f"registry.documents[{index}]"
        if not isinstance(raw, Mapping):
            raise VisualRegistryError(f"{context} must be an object")
        _strict(raw, required, context)
        document_id = _text(raw["id"], f"{context}.id")
        if document_id in ids:
            raise VisualRegistryError(f"duplicate document id: {document_id}")
        ids.add(document_id)
        group = _text(raw["document_group"], f"{context}.document_group")
        split = _text(raw["split"], f"{context}.split")
        if split not in ALLOWED_SPLITS:
            raise VisualRegistryError(f"{context}.split is unsupported: {split!r}")
        previous = group_splits.setdefault(group, split)
        if previous != split:
            raise VisualRegistryError(f"document group {group!r} leaks across splits")
        digest = _text(raw["content_sha256"], f"{context}.content_sha256")
        if SHA256.fullmatch(digest) is None:
            raise VisualRegistryError(f"{context}.content_sha256 must be lowercase SHA-256")
        owner = hash_owners.setdefault(digest, (group, split))
        if owner != (group, split):
            raise VisualRegistryError(
                f"content hash {digest} is assigned to multiple groups or splits"
            )
        redistribution = _text(raw["redistribution"], f"{context}.redistribution")
        if redistribution not in ALLOWED_REDISTRIBUTION:
            raise VisualRegistryError(
                f"{context}.redistribution must be one of {sorted(ALLOWED_REDISTRIBUTION)}"
            )
        identity = Identity.parse(raw["identity"], f"{context}.identity")
        review = Review.parse(raw["review"], f"{context}.review")
        if split in {"calibration", "evaluation"} and review.status != "reviewed":
            raise VisualRegistryError(f"{context} {split} annotations must be reviewed")
        cases_raw = raw["cases"]
        if not isinstance(cases_raw, list) or not cases_raw:
            raise VisualRegistryError(f"{context}.cases must be a non-empty array")
        cases: list[VisualCase] = []
        local_ids: set[str] = set()
        for case_index, case_raw in enumerate(cases_raw):
            case_context = f"{context}.cases[{case_index}]"
            case = VisualCase.parse(case_raw, case_context)
            qualified_id = f"{document_id}/{case.case_id}"
            if case.case_id in local_ids or qualified_id in case_ids:
                raise VisualRegistryError(f"duplicate visual case id: {qualified_id}")
            local_ids.add(case.case_id)
            case_ids.add(qualified_id)
            _validate_identity_relationship(case, identity, case_context)
            cases.append(case)
        positive_regions = {case.region_type for case in cases if case.label == POSITIVE}
        if not REQUIRED_POSITIVE_REGIONS.issubset(positive_regions):
            missing = sorted(REQUIRED_POSITIVE_REGIONS - positive_regions)
            raise VisualRegistryError(f"{context} is missing positive regions: {missing}")
        if not any(case.label != POSITIVE for case in cases):
            raise VisualRegistryError(f"{context} must include an adversarial visual case")
        positive_views = {(case.region_type, case.view) for case in cases if case.label == POSITIVE}
        for case in cases:
            if case.label == "wrong_view" and (
                case.view not in {"top", "bottom"}
                or not any(
                    region_type == case.region_type
                    and positive_view in {"top", "bottom"}
                    and positive_view != case.view
                    for region_type, positive_view in positive_views
                )
            ):
                raise VisualRegistryError(
                    f"{context} wrong_view must oppose a positive top/bottom view"
                )
        documents.append(
            VisualDocument(
                document_id,
                group,
                split,
                _text(raw["category"], f"{context}.category"),
                Source.parse(raw["source"], f"{context}.source"),
                digest,
                redistribution,
                _text(raw["license_note"], f"{context}.license_note"),
                identity,
                review,
                tuple(cases),
            )
        )

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return VisualRegistry(tuple(documents), hashlib.sha256(encoded).hexdigest())


def bind_prediction_scores(
    registry: VisualRegistry, scores: Mapping[str, Any]
) -> tuple[Prediction, ...]:
    """Bind untrusted adapter scores to registry-owned labels and splits.

    Adapters are never allowed to supply their own ground-truth label, split,
    or document group. They produce exactly one score for each qualified case
    ID; the reviewed registry owns everything else.
    """
    expected = {
        f"{document.document_id}/{case.case_id}": (document, case)
        for document in registry.documents
        for case in document.cases
    }
    missing = set(expected) - set(scores)
    unknown = set(scores) - set(expected)
    if missing or unknown:
        raise VisualRegistryError(
            f"adapter score keys invalid: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    try:
        return tuple(
            Prediction.parse(
                {
                    "case_id": case_id,
                    "document_group": document.document_group,
                    "split": document.split,
                    "label": case.label,
                    "score": scores[case_id],
                },
                f"adapter score {case_id}",
            )
            for case_id, (document, case) in sorted(expected.items())
        )
    except VisualMetricError as exc:
        raise VisualRegistryError(str(exc)) from exc

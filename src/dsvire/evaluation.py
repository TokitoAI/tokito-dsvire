"""Reproducible real-PDF identity evaluation with explicit provenance."""

from __future__ import annotations

import dataclasses
import hashlib
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .pipeline import DatasheetIdentity, RetrievalError, retrieve_symbol_evidence

REGISTRY_VERSION = "dsvire.identity-eval-registry.v1"
ALLOWED_SPLITS = {"development", "evaluation"}
ALLOWED_REDISTRIBUTION = {"download_only", "redistributable"}
SHA256 = re.compile(r"[0-9a-f]{64}")


class RegistryError(ValueError):
    """The evaluation registry or fetched source violates its contract."""


def _strict_keys(value: Mapping[str, Any], required: set[str], context: str) -> None:
    keys = set(value)
    missing = required - keys
    unknown = keys - required
    if missing or unknown:
        raise RegistryError(
            f"{context} keys invalid: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _required_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{context} must be non-empty text")
    return value.strip()


@dataclasses.dataclass(frozen=True)
class IdentityCase:
    manufacturer: str
    mpn: str
    package: str

    @classmethod
    def parse(cls, value: Any, context: str) -> IdentityCase:
        if not isinstance(value, dict):
            raise RegistryError(f"{context} must be an object")
        _strict_keys(value, {"manufacturer", "mpn", "package"}, context)
        return cls(
            _required_text(value["manufacturer"], f"{context}.manufacturer"),
            _required_text(value["mpn"], f"{context}.mpn"),
            _required_text(value["package"], f"{context}.package"),
        )

    def pipeline_identity(self, source_url: str) -> DatasheetIdentity:
        return DatasheetIdentity(self.manufacturer, self.mpn, self.package, source_url)


@dataclasses.dataclass(frozen=True)
class NegativeCase:
    case_id: str
    identity: IdentityCase
    expected_error_contains: str


@dataclasses.dataclass(frozen=True)
class DocumentCase:
    case_id: str
    document_group: str
    split: str
    source_url: str
    source_revision: str
    content_sha256: str
    redistribution: str
    license_note: str
    identity: IdentityCase
    negatives: tuple[NegativeCase, ...]


@dataclasses.dataclass(frozen=True)
class IdentityRegistry:
    documents: tuple[DocumentCase, ...]


def load_registry_data(value: Any) -> IdentityRegistry:
    if not isinstance(value, dict):
        raise RegistryError("registry must be an object")
    _strict_keys(value, {"schema_version", "documents"}, "registry")
    if value["schema_version"] != REGISTRY_VERSION:
        raise RegistryError(f"unsupported registry version: {value['schema_version']!r}")
    if not isinstance(value["documents"], list) or not value["documents"]:
        raise RegistryError("registry.documents must be a non-empty array")

    documents: list[DocumentCase] = []
    ids: set[str] = set()
    group_splits: dict[str, str] = {}
    hash_owners: dict[str, tuple[str, str]] = {}
    for index, raw in enumerate(value["documents"]):
        context = f"registry.documents[{index}]"
        if not isinstance(raw, dict):
            raise RegistryError(f"{context} must be an object")
        _strict_keys(
            raw,
            {
                "id",
                "document_group",
                "split",
                "source",
                "content_sha256",
                "redistribution",
                "license_note",
                "identity",
                "negatives",
            },
            context,
        )
        case_id = _required_text(raw["id"], f"{context}.id")
        if case_id in ids:
            raise RegistryError(f"duplicate document id: {case_id}")
        ids.add(case_id)
        group = _required_text(raw["document_group"], f"{context}.document_group")
        split = _required_text(raw["split"], f"{context}.split")
        if split not in ALLOWED_SPLITS:
            raise RegistryError(f"{context}.split must be one of {sorted(ALLOWED_SPLITS)}")
        previous_split = group_splits.setdefault(group, split)
        if previous_split != split:
            raise RegistryError(f"document group {group!r} leaks across splits")

        source = raw["source"]
        if not isinstance(source, dict):
            raise RegistryError(f"{context}.source must be an object")
        _strict_keys(source, {"url", "revision"}, f"{context}.source")
        source_url = _required_text(source["url"], f"{context}.source.url")
        if not source_url.startswith("https://"):
            raise RegistryError(f"{context}.source.url must use HTTPS")
        revision = _required_text(source["revision"], f"{context}.source.revision")
        digest = _required_text(raw["content_sha256"], f"{context}.content_sha256")
        if SHA256.fullmatch(digest) is None:
            raise RegistryError(f"{context}.content_sha256 must be lowercase SHA-256")
        owner = hash_owners.setdefault(digest, (group, split))
        if owner != (group, split):
            raise RegistryError(f"content hash {digest} is assigned to multiple groups or splits")

        redistribution = _required_text(raw["redistribution"], f"{context}.redistribution")
        if redistribution not in ALLOWED_REDISTRIBUTION:
            raise RegistryError(
                f"{context}.redistribution must be one of {sorted(ALLOWED_REDISTRIBUTION)}"
            )
        negatives_raw = raw["negatives"]
        if not isinstance(negatives_raw, list) or not negatives_raw:
            raise RegistryError(f"{context}.negatives must be a non-empty array")
        negatives: list[NegativeCase] = []
        negative_ids: set[str] = set()
        for negative_index, negative in enumerate(negatives_raw):
            negative_context = f"{context}.negatives[{negative_index}]"
            if not isinstance(negative, dict):
                raise RegistryError(f"{negative_context} must be an object")
            _strict_keys(
                negative,
                {"id", "identity", "expected_error_contains"},
                negative_context,
            )
            negative_id = _required_text(negative["id"], f"{negative_context}.id")
            if negative_id in negative_ids:
                raise RegistryError(f"duplicate negative id in {case_id}: {negative_id}")
            negative_ids.add(negative_id)
            negatives.append(
                NegativeCase(
                    negative_id,
                    IdentityCase.parse(negative["identity"], f"{negative_context}.identity"),
                    _required_text(
                        negative["expected_error_contains"],
                        f"{negative_context}.expected_error_contains",
                    ),
                )
            )

        documents.append(
            DocumentCase(
                case_id,
                group,
                split,
                source_url,
                revision,
                digest,
                redistribution,
                _required_text(raw["license_note"], f"{context}.license_note"),
                IdentityCase.parse(raw["identity"], f"{context}.identity"),
                tuple(negatives),
            )
        )
    return IdentityRegistry(tuple(documents))


def evaluate_registry(
    registry: IdentityRegistry,
    fetch: Callable[[DocumentCase], bytes],
    *,
    output_root: Path | None = None,
) -> dict[str, Any]:
    root_context = (
        tempfile.TemporaryDirectory(prefix="dsvire-identity-eval-") if output_root is None else None
    )
    root = Path(root_context.name) if root_context is not None else output_root
    assert root is not None
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    positive_passed = 0
    negative_abstained = 0
    silent_wrong = 0
    negative_wrong_reason = 0
    try:
        for document in registry.documents:
            payload = fetch(document)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != document.content_sha256:
                raise RegistryError(
                    f"{document.case_id}: source SHA-256 mismatch; expected "
                    f"{document.content_sha256}, got {digest}"
                )
            document_result: dict[str, Any] = {
                "id": document.case_id,
                "document_group": document.document_group,
                "split": document.split,
                "content_sha256": digest,
                "positive": {},
                "negatives": [],
            }
            try:
                bundle = retrieve_symbol_evidence(
                    payload,
                    document.identity.pipeline_identity(document.source_url),
                    root / document.case_id / "positive",
                )
                region_types = sorted(
                    region["type"]
                    for region in bundle["regions"]
                    if region["verification"]["outcome"] == "accepted"
                )
                required = {"package", "pinout", "table"}
                passed = required.issubset(region_types)
                document_result["positive"] = {
                    "outcome": "pass" if passed else "fail",
                    "accepted_region_types": region_types,
                }
                positive_passed += int(passed)
            except RetrievalError as exc:
                document_result["positive"] = {
                    "outcome": "fail",
                    "error": str(exc),
                }

            for negative in document.negatives:
                try:
                    retrieve_symbol_evidence(
                        payload,
                        negative.identity.pipeline_identity(document.source_url),
                        root / document.case_id / f"negative-{negative.case_id}",
                    )
                except RetrievalError as exc:
                    error = str(exc)
                    matched = negative.expected_error_contains in error
                    negative_abstained += int(matched)
                    negative_wrong_reason += int(not matched)
                    document_result["negatives"].append(
                        {
                            "id": negative.case_id,
                            "outcome": "abstained" if matched else "wrong_reason",
                            "error": error,
                        }
                    )
                else:
                    silent_wrong += 1
                    document_result["negatives"].append(
                        {"id": negative.case_id, "outcome": "silently_accepted"}
                    )
            results.append(document_result)
    finally:
        if root_context is not None:
            root_context.cleanup()

    negatives_expected = sum(len(document.negatives) for document in registry.documents)
    metrics = {
        "documents": len(registry.documents),
        "positives_expected": len(registry.documents),
        "positives_passed": positive_passed,
        "negatives_expected": negatives_expected,
        "negatives_abstained_with_expected_reason": negative_abstained,
        "negative_wrong_reason": negative_wrong_reason,
        "silent_wrong_identity_acceptances": silent_wrong,
    }
    gate_passed = (
        positive_passed == len(registry.documents)
        and negative_abstained == negatives_expected
        and silent_wrong == 0
        and negative_wrong_reason == 0
    )
    return {
        "schema_version": "dsvire.identity-eval-result.v2",
        "gate_passed": gate_passed,
        "metrics": metrics,
        "documents": results,
    }

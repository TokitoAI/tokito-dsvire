"""Deterministic coverage ledger for the source-free visual corpus registry."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .visual_registry import VisualRegistry

POLICY_VERSION = "dsvire.corpus-coverage-policy.v1"
QUERY_REGISTRY_VERSION = "dsvire.query-registry.v1"
RESULT_VERSION = "dsvire.corpus-coverage.v1"


class CorpusCoverageError(ValueError):
    """The coverage policy or registry cannot produce an honest ledger."""


def _positive_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CorpusCoverageError(f"{context} must be a positive integer")
    return value


def _strings(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CorpusCoverageError(f"{context} must be a non-empty array")
    result = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise CorpusCoverageError(f"{context} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise CorpusCoverageError(f"{context} contains duplicates")
    return result


@dataclasses.dataclass(frozen=True)
class CoveragePolicy:
    document_target: int
    query_target: int
    required_splits: tuple[str, ...]
    required_case_labels: tuple[str, ...]
    required_region_types: tuple[str, ...]
    category_strata: Mapping[str, tuple[str, ...]]
    content_sha256: str


@dataclasses.dataclass(frozen=True)
class QueryRecord:
    query_id: str
    document_group: str
    split: str
    query_text: str
    query_type: str
    relevant_case_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class QueryRegistry:
    queries: tuple[QueryRecord, ...]
    content_sha256: str


def load_coverage_policy(value: Any) -> CoveragePolicy:
    if not isinstance(value, Mapping):
        raise CorpusCoverageError("policy must be an object")
    required = {
        "schema_version",
        "targets",
        "required_splits",
        "required_case_labels",
        "required_region_types",
        "category_strata",
    }
    if set(value) != required:
        raise CorpusCoverageError(
            f"policy keys invalid: missing={sorted(required - set(value))}, "
            f"unknown={sorted(set(value) - required)}"
        )
    if value["schema_version"] != POLICY_VERSION:
        raise CorpusCoverageError(f"unsupported policy version: {value['schema_version']!r}")
    targets = value["targets"]
    if not isinstance(targets, Mapping) or set(targets) != {"documents", "queries"}:
        raise CorpusCoverageError("policy.targets must contain only documents and queries")
    strata_raw = value["category_strata"]
    if not isinstance(strata_raw, Mapping) or not strata_raw:
        raise CorpusCoverageError("policy.category_strata must be a non-empty object")
    strata: dict[str, tuple[str, ...]] = {}
    owners: dict[str, str] = {}
    for name, categories_raw in strata_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise CorpusCoverageError("policy.category_strata names must be non-empty")
        categories = _strings(categories_raw, f"policy.category_strata.{name}")
        for category in categories:
            previous = owners.setdefault(category, name)
            if previous != name:
                raise CorpusCoverageError(
                    f"category {category!r} belongs to multiple strata: {previous!r}, {name!r}"
                )
        strata[name] = categories
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return CoveragePolicy(
        _positive_int(targets["documents"], "policy.targets.documents"),
        _positive_int(targets["queries"], "policy.targets.queries"),
        _strings(value["required_splits"], "policy.required_splits"),
        _strings(value["required_case_labels"], "policy.required_case_labels"),
        _strings(value["required_region_types"], "policy.required_region_types"),
        strata,
        hashlib.sha256(encoded).hexdigest(),
    )


def load_query_registry(value: Any, registry: VisualRegistry) -> QueryRegistry:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "queries"}:
        raise CorpusCoverageError("query registry must contain only schema_version and queries")
    if value["schema_version"] != QUERY_REGISTRY_VERSION:
        raise CorpusCoverageError(
            f"unsupported query registry version: {value['schema_version']!r}"
        )
    raw_queries = value["queries"]
    if not isinstance(raw_queries, list):
        raise CorpusCoverageError("query registry queries must be an array")
    documents_by_group = {document.document_group: document for document in registry.documents}
    case_owners = {
        f"{document.document_id}/{case.case_id}": (document, case)
        for document in registry.documents
        for case in document.cases
    }
    records: list[QueryRecord] = []
    ids: set[str] = set()
    for index, raw in enumerate(raw_queries):
        context = f"query registry queries[{index}]"
        required = {
            "id",
            "document_group",
            "split",
            "query_text",
            "query_type",
            "relevant_case_ids",
        }
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise CorpusCoverageError(f"{context} keys are invalid")
        query_id = raw["id"]
        document_group = raw["document_group"]
        split = raw["split"]
        query_text = raw["query_text"]
        query_type = raw["query_type"]
        for field, item in (
            ("id", query_id),
            ("document_group", document_group),
            ("split", split),
            ("query_text", query_text),
            ("query_type", query_type),
        ):
            if not isinstance(item, str) or not item.strip():
                raise CorpusCoverageError(f"{context}.{field} must be non-empty text")
        if query_id in ids:
            raise CorpusCoverageError(f"duplicate query id: {query_id}")
        ids.add(query_id)
        document = documents_by_group.get(document_group)
        if document is None:
            raise CorpusCoverageError(f"{context} references unknown document group")
        if split != document.split:
            raise CorpusCoverageError(f"{context} split differs from its document group")
        relevant = _strings(raw["relevant_case_ids"], f"{context}.relevant_case_ids")
        for case_id in relevant:
            owner = case_owners.get(case_id)
            if owner is None:
                raise CorpusCoverageError(f"{context} references unknown case {case_id!r}")
            owner_document, case = owner
            if owner_document.document_group != document_group or case.label != "positive":
                raise CorpusCoverageError(
                    f"{context} relevant cases must be positive cases in its document group"
                )
            if case.region_type != query_type:
                raise CorpusCoverageError(f"{context} relevant case type differs from query_type")
        records.append(
            QueryRecord(
                query_id,
                document_group,
                split,
                query_text,
                query_type,
                relevant,
            )
        )
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return QueryRegistry(tuple(records), hashlib.sha256(encoded).hexdigest())


def _counts(values: list[str], ordered_keys: tuple[str, ...] | None = None) -> dict[str, int]:
    counter = Counter(values)
    keys = ordered_keys or tuple(sorted(counter))
    return {key: counter.get(key, 0) for key in keys}


def audit_corpus_coverage(
    registry: VisualRegistry, policy: CoveragePolicy, query_registry: QueryRegistry
) -> dict[str, Any]:
    documents = registry.documents
    categories = {document.category for document in documents}
    category_owners = {
        category: stratum
        for stratum, members in policy.category_strata.items()
        for category in members
    }
    unsupported = sorted(categories - set(category_owners))
    if unsupported:
        raise CorpusCoverageError(
            f"registry categories are not assigned to a stratum: {unsupported}"
        )

    splits = {document.split for document in documents}
    missing_splits = sorted(set(policy.required_splits) - splits)
    if missing_splits:
        raise CorpusCoverageError(f"registry is missing required splits: {missing_splits}")

    cases = [case for document in documents for case in document.cases]
    labels = {case.label for case in cases}
    regions = {case.region_type for case in cases}
    if labels - set(policy.required_case_labels):
        raise CorpusCoverageError(
            f"registry contains unsupported labels: {sorted(labels - set(policy.required_case_labels))}"
        )
    if regions - set(policy.required_region_types):
        raise CorpusCoverageError(
            f"registry contains unsupported region types: {sorted(regions - set(policy.required_region_types))}"
        )

    independent = 0
    agent = 0
    unreviewed = 0
    for document in documents:
        if document.review.status != "reviewed":
            unreviewed += 1
        elif all(reviewer.startswith("agent:") for reviewer in document.review.reviewers):
            agent += 1
        else:
            independent += 1

    split_documents = _counts([document.split for document in documents], policy.required_splits)
    split_families = {
        split: len({d.document_group for d in documents if d.split == split})
        for split in policy.required_splits
    }
    split_cases = {
        split: sum(len(d.cases) for d in documents if d.split == split)
        for split in policy.required_splits
    }
    stratum_documents = {
        stratum: sum(category_owners[d.category] == stratum for d in documents)
        for stratum in policy.category_strata
    }
    document_count = len(documents)
    query_count = len(query_registry.queries)
    return {
        "schema_version": RESULT_VERSION,
        "registry_sha256": registry.content_sha256,
        "query_registry_sha256": query_registry.content_sha256,
        "policy_sha256": policy.content_sha256,
        "targets": {"documents": policy.document_target, "queries": policy.query_target},
        "achieved": {
            "documents": document_count,
            "document_families": len({document.document_group for document in documents}),
            "explicit_queries": query_count,
            "annotated_cases": len(cases),
            "manufacturers": len({document.identity.manufacturer for document in documents}),
            "categories": len(categories),
        },
        "remaining": {
            "documents": max(0, policy.document_target - document_count),
            "queries": max(0, policy.query_target - query_count),
        },
        "target_met": document_count >= policy.document_target
        and query_count >= policy.query_target,
        "splits": {
            split: {
                "documents": split_documents[split],
                "families": split_families[split],
                "annotated_cases": split_cases[split],
            }
            for split in policy.required_splits
        },
        "case_labels": _counts([case.label for case in cases], policy.required_case_labels),
        "case_intents": _counts([case.region_type for case in cases], policy.required_region_types),
        "query_intents": _counts(
            [query.query_type for query in query_registry.queries], policy.required_region_types
        ),
        "category_strata_documents": stratum_documents,
        "review": {
            "independent_human_documents": independent,
            "owner_authorized_agent_documents": agent,
            "unreviewed_documents": unreviewed,
        },
        "limitations": [
            "annotated visual cases are not natural-language benchmark queries",
            "owner-authorized agent review is not independent human annotation",
            "download-only source records do not establish legal approval",
            "coverage counts do not establish retrieval accuracy or representativeness",
        ],
    }

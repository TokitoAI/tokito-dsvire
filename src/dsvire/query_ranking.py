"""Strict judged-pool ranking contract and model-independent retrieval metrics."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .corpus_coverage import QueryRecord, QueryRegistry
from .visual_registry import VisualRegistry

RANKING_VERSION = "dsvire.query-ranking.v1"
RESULT_VERSION = "dsvire.query-ranking-result.v1"
METRIC_VERSION = "dsvire.query-ranking-metrics@1.0.0"
SHA256 = re.compile(r"[0-9a-f]{64}")


class QueryRankingError(ValueError):
    """A ranking artifact is incomplete, injected, or otherwise invalid."""


@dataclasses.dataclass(frozen=True)
class RankedCandidate:
    case_id: str
    score: float


@dataclasses.dataclass(frozen=True)
class QueryRanking:
    query_id: str
    candidates: tuple[RankedCandidate, ...]


@dataclasses.dataclass(frozen=True)
class RankingArtifact:
    system_id: str
    system_sha256: str
    rankings: tuple[QueryRanking, ...]
    content_sha256: str


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QueryRankingError(f"{context} must be non-empty text")
    return value.strip()


def load_ranking_artifact(
    value: Any, query_registry: QueryRegistry, visual_registry: VisualRegistry
) -> RankingArtifact:
    if not isinstance(value, Mapping):
        raise QueryRankingError("ranking artifact must be an object")
    required = {
        "schema_version",
        "query_registry_sha256",
        "visual_registry_sha256",
        "system",
        "rankings",
    }
    if set(value) != required:
        raise QueryRankingError("ranking artifact keys are invalid")
    if value["schema_version"] != RANKING_VERSION:
        raise QueryRankingError(f"unsupported ranking version: {value['schema_version']!r}")
    if value["query_registry_sha256"] != query_registry.content_sha256:
        raise QueryRankingError("query registry digest mismatch")
    if value["visual_registry_sha256"] != visual_registry.content_sha256:
        raise QueryRankingError("visual registry digest mismatch")
    system = value["system"]
    if not isinstance(system, Mapping) or set(system) != {"id", "sha256"}:
        raise QueryRankingError("system must contain only id and sha256")
    system_id = _text(system["id"], "system.id")
    system_sha256 = system["sha256"]
    if not isinstance(system_sha256, str) or SHA256.fullmatch(system_sha256) is None:
        raise QueryRankingError("system.sha256 must be lowercase SHA-256")
    raw_rankings = value["rankings"]
    if not isinstance(raw_rankings, list):
        raise QueryRankingError("rankings must be an array")
    queries = {query.query_id: query for query in query_registry.queries}
    ranking_ids: set[str] = set()
    rankings: list[QueryRanking] = []
    for index, raw in enumerate(raw_rankings):
        context = f"rankings[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != {"query_id", "candidates"}:
            raise QueryRankingError(f"{context} keys are invalid")
        query_id = _text(raw["query_id"], f"{context}.query_id")
        query = queries.get(query_id)
        if query is None:
            raise QueryRankingError(f"{context} references unknown query")
        if query_id in ranking_ids:
            raise QueryRankingError(f"duplicate ranking for query {query_id!r}")
        ranking_ids.add(query_id)
        raw_candidates = raw["candidates"]
        if not isinstance(raw_candidates, list):
            raise QueryRankingError(f"{context}.candidates must be an array")
        allowed = {case_id for case_id, _grade in query.relevance_judgments} | set(
            query.hard_negative_case_ids
        )
        candidate_ids: set[str] = set()
        candidates: list[RankedCandidate] = []
        previous_score = math.inf
        for candidate_index, candidate in enumerate(raw_candidates):
            candidate_context = f"{context}.candidates[{candidate_index}]"
            if not isinstance(candidate, Mapping) or set(candidate) != {"case_id", "score"}:
                raise QueryRankingError(f"{candidate_context} keys are invalid")
            case_id = _text(candidate["case_id"], f"{candidate_context}.case_id")
            score = candidate["score"]
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not math.isfinite(score)
            ):
                raise QueryRankingError(f"{candidate_context}.score must be finite")
            score = float(score)
            if case_id not in allowed:
                raise QueryRankingError(f"{candidate_context} injects an unjudged candidate")
            if case_id in candidate_ids:
                raise QueryRankingError(f"{context} contains duplicate candidates")
            if score > previous_score:
                raise QueryRankingError(f"{context} candidates must be score-descending")
            previous_score = score
            candidate_ids.add(case_id)
            candidates.append(RankedCandidate(case_id, score))
        rankings.append(QueryRanking(query_id, tuple(candidates)))
    missing = set(queries) - ranking_ids
    if missing:
        raise QueryRankingError(f"rankings missing {len(missing)} queries")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return RankingArtifact(
        system_id, system_sha256, tuple(rankings), hashlib.sha256(encoded).hexdigest()
    )


def _query_metrics(query: QueryRecord, ranking: QueryRanking, k: int) -> dict[str, Any]:
    grades = dict(query.relevance_judgments)
    hard_negatives = set(query.hard_negative_case_ids)
    top = ranking.candidates[:k]
    gains = [2 ** grades.get(candidate.case_id, 0) - 1 for candidate in top]
    ideal = sorted((2**grade - 1 for grade in grades.values()), reverse=True)[:k]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, 1))
    idcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, 1))
    relevant_seen = 0
    precision_sum = 0.0
    first_relevant_rank: int | None = None
    for rank, candidate in enumerate(ranking.candidates, 1):
        if candidate.case_id in grades:
            relevant_seen += 1
            precision_sum += relevant_seen / rank
            if first_relevant_rank is None:
                first_relevant_rank = rank
    relevant_top = sum(candidate.case_id in grades for candidate in top)
    return {
        "query_id": query.query_id,
        "split": query.split,
        "query_type": query.query_type,
        "returned": len(ranking.candidates),
        "ndcg_at_5": dcg / idcg if idcg else 0.0,
        "recall_at_5": relevant_top / len(grades),
        "average_precision": precision_sum / len(grades),
        "reciprocal_rank": 1 / first_relevant_rank if first_relevant_rank else 0.0,
        "hard_negatives_at_5": sum(candidate.case_id in hard_negatives for candidate in top),
        "abstained": not ranking.candidates,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if count == 0:
        return {
            "queries": 0,
            "queries_with_results": 0,
            "coverage": 0.0,
            "ndcg_at_5": 0.0,
            "recall_at_5": 0.0,
            "map": 0.0,
            "mrr": 0.0,
            "queries_with_hard_negative_at_5": 0,
            "hard_negatives_at_5": 0,
        }
    return {
        "queries": count,
        "queries_with_results": sum(not row["abstained"] for row in rows),
        "coverage": sum(not row["abstained"] for row in rows) / count,
        "ndcg_at_5": sum(row["ndcg_at_5"] for row in rows) / count,
        "recall_at_5": sum(row["recall_at_5"] for row in rows) / count,
        "map": sum(row["average_precision"] for row in rows) / count,
        "mrr": sum(row["reciprocal_rank"] for row in rows) / count,
        "queries_with_hard_negative_at_5": sum(row["hard_negatives_at_5"] > 0 for row in rows),
        "hard_negatives_at_5": sum(row["hard_negatives_at_5"] for row in rows),
    }


def evaluate_rankings(
    query_registry: QueryRegistry, artifact: RankingArtifact, *, k: int = 5
) -> dict[str, Any]:
    if k != 5:
        raise QueryRankingError("metric contract currently requires k=5")
    queries = {query.query_id: query for query in query_registry.queries}
    rows = [_query_metrics(queries[item.query_id], item, k) for item in artifact.rankings]
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "split": defaultdict(list),
        "query_type": defaultdict(list),
    }
    for row in rows:
        groups["split"][row["split"]].append(row)
        groups["query_type"][row["query_type"]].append(row)
    return {
        "schema_version": RESULT_VERSION,
        "metric_version": METRIC_VERSION,
        "query_registry_sha256": query_registry.content_sha256,
        "ranking_sha256": artifact.content_sha256,
        "system": {"id": artifact.system_id, "sha256": artifact.system_sha256},
        "scope": "closed_judged_pool",
        "cutoff": k,
        "metrics": _aggregate(rows),
        "by_split": {name: _aggregate(values) for name, values in sorted(groups["split"].items())},
        "by_query_type": {
            name: _aggregate(values) for name, values in sorted(groups["query_type"].items())
        },
        "queries": rows,
        "limitations": [
            "closed judged-pool metrics do not measure full-corpus retrieval",
            "deterministic-template development queries are not held-out or independently reviewed",
            "this artifact cannot authorize automated publication",
        ],
    }

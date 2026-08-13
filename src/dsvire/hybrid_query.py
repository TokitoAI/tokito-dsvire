"""Deterministic BM25/dense/RRF/bounded-MaxSim retrieval over validated packs."""

from __future__ import annotations

import hashlib
import inspect
import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from .retrieval_pack import ALLOWED_REGION_TYPES, RetrievalPack

TOKEN = re.compile(r"[a-z0-9]+")
TYPE_TERMS = {
    "pinout": {"pin", "pins", "pinout", "terminal", "terminals", "lead", "leads"},
    "table": {"table", "rating", "ratings", "characteristic", "characteristics", "electrical"},
    "package": {"package", "footprint", "dimension", "dimensions", "drawing", "land", "outline"},
}
TYPE_PRIORITY = {"pinout": 0, "package": 1, "table": 2}
MAX_QUERY_BYTES = 8_192
MAX_TOP_N = 10_000
MAX_MAXSIM_K = 1_000
MAX_QUERY_VECTORS = 512
SYSTEM_ID = "dsvire.hybrid-query-core@1.0.0"
MaxSimScorer = Callable[[Sequence[Sequence[float]], Sequence[Sequence[float]], int], float]


class HybridQueryError(ValueError):
    """A query or encoder output violates the bounded retrieval contract."""


@dataclass(frozen=True)
class HybridHit:
    region_id: str
    score: float
    bm25_score: float
    dense_score: float
    maxsim_score: float


@dataclass(frozen=True)
class HybridResult:
    routed_types: tuple[str, str]
    considered: int
    maxsim_evaluated: int
    prefiltered_region_ids: tuple[str, ...]
    hits: tuple[HybridHit, ...]


def implementation_sha256() -> str:
    source = "\n".join(
        inspect.getsource(component).replace("\r\n", "\n")
        for component in (route_types, _bm25, _rank, maxsim, maxsim_numpy, hybrid_query)
    )
    return hashlib.sha256(source.encode()).hexdigest()


def _tokens(value: str) -> list[str]:
    return TOKEN.findall(value.casefold())


def route_types(query: str) -> tuple[str, str]:
    terms = set(_tokens(query))
    scores = {name: len(terms & hints) for name, hints in TYPE_TERMS.items()}
    ordered = sorted(ALLOWED_REGION_TYPES, key=lambda name: (-scores[name], TYPE_PRIORITY[name]))
    return ordered[0], ordered[1]


def _checked_vector(value: Sequence[float], dimension: int, context: str) -> tuple[float, ...]:
    if len(value) != dimension:
        raise HybridQueryError(f"{context} must have dimension {dimension}")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise HybridQueryError(f"{context} must contain only numbers")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) and abs(item) <= 1_000_000 for item in result):
        raise HybridQueryError(f"{context} contains an invalid value")
    return result


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


def maxsim(
    query_vectors: Sequence[Sequence[float]],
    document_vectors: Sequence[Sequence[float]],
    dimension: int,
) -> float:
    """Exact ColBERT-style sum-of-query-token maxima using bounded scalar working memory."""
    if not query_vectors or not document_vectors:
        raise HybridQueryError("MaxSim vectors must be non-empty")
    queries = tuple(_checked_vector(item, dimension, "query_multi") for item in query_vectors)
    documents = tuple(
        _checked_vector(item, dimension, "document_multi") for item in document_vectors
    )
    score = math.fsum(max(_dot(query, document) for document in documents) for query in queries)
    if not math.isfinite(score):
        raise HybridQueryError("MaxSim produced a non-finite score")
    return score


def maxsim_numpy(
    query_vectors: Sequence[Sequence[float]],
    document_vectors: Sequence[Sequence[float]],
    dimension: int,
) -> float:
    """Exact-shape float64 MaxSim accelerated by NumPy matrix multiplication."""
    if not query_vectors or not document_vectors or not 1 <= dimension <= 8_192:
        raise HybridQueryError("MaxSim vectors or dimension are invalid")
    try:
        numpy: Any = import_module("numpy")
        query = numpy.asarray(query_vectors, dtype=numpy.float64)
        document = numpy.asarray(document_vectors, dtype=numpy.float64)
        if query.shape != (len(query_vectors), dimension) or document.shape != (
            len(document_vectors),
            dimension,
        ):
            raise HybridQueryError("MaxSim vector shape is invalid")
        if not numpy.isfinite(query).all() or not numpy.isfinite(document).all():
            raise HybridQueryError("MaxSim vectors contain invalid values")
        score = float(numpy.max(query @ document.T, axis=1).sum(dtype=numpy.float64))
    except HybridQueryError:
        raise
    except Exception as exc:
        raise HybridQueryError("vectorized MaxSim failed") from exc
    if not math.isfinite(score):
        raise HybridQueryError("MaxSim produced a non-finite score")
    return score


def _bm25(
    query_terms: list[str], documents: Sequence[str], *, k1: float = 1.2, b: float = 0.75
) -> list[float]:
    tokenized = [_tokens(text) for text in documents]
    average = math.fsum(len(item) for item in tokenized) / len(tokenized)
    query_counts = Counter(query_terms)
    frequencies = {term: sum(term in doc for doc in tokenized) for term in query_counts}
    scores: list[float] = []
    for doc in tokenized:
        counts = Counter(doc)
        score = 0.0
        for term, query_frequency in query_counts.items():
            tf, df = counts[term], frequencies[term]
            if not tf:
                continue
            inverse = math.log(1.0 + (len(tokenized) - df + 0.5) / (df + 0.5))
            length_norm = 1.0 - b + b * len(doc) / average if average else 1.0
            score += query_frequency * inverse * tf * (k1 + 1.0) / (tf + k1 * length_norm)
        scores.append(score)
    return scores


def _rank(ids: Sequence[str], scores: Sequence[float]) -> list[str]:
    return [
        ids[index]
        for index in sorted(range(len(ids)), key=lambda index: (-scores[index], ids[index]))
    ]


def hybrid_query(
    pack: RetrievalPack,
    query: str,
    dense_vector: Sequence[float],
    multi_vectors: Sequence[Sequence[float]],
    *,
    top_n: int = 100,
    maxsim_k: int = 32,
    limit: int = 5,
    rrf_k: int = 60,
    maxsim_scorer: MaxSimScorer = maxsim,
) -> HybridResult:
    """Run the Bible cascade core without consulting identity or relevance metadata."""
    if not isinstance(query, str) or not query.strip() or len(query.encode()) > MAX_QUERY_BYTES:
        raise HybridQueryError("query is empty or outside its byte limit")
    dense = _checked_vector(dense_vector, pack.dense_dim, "dense_vector")
    # Validate query multi-vectors before any partial ranking is returned.
    if not 1 <= len(multi_vectors) <= MAX_QUERY_VECTORS:
        raise HybridQueryError("multi_vectors are outside their token limit")
    checked_multi = tuple(
        _checked_vector(item, pack.multi_dim, "multi_vectors") for item in multi_vectors
    )
    if not 1 <= top_n <= min(MAX_TOP_N, len(pack.regions)):
        raise HybridQueryError("top_n is outside its bounded range")
    if not 1 <= maxsim_k <= min(MAX_MAXSIM_K, top_n) or not 1 <= limit <= maxsim_k:
        raise HybridQueryError("maxsim_k or limit is outside its bounded range")
    if not 1 <= rrf_k <= 10_000:
        raise HybridQueryError("rrf_k is outside its bounded range")
    ids = [region.id for region in pack.regions]
    bm25_scores = _bm25(
        _tokens(query),
        ["\n".join(value for _name, value in region.text_fields) for region in pack.regions],
    )
    dense_scores = [_dot(dense, region.dense) for region in pack.regions]
    bm25_order, dense_order = _rank(ids, bm25_scores), _rank(ids, dense_scores)
    fused: dict[str, float] = {}
    for order in (bm25_order[:top_n], dense_order[:top_n]):
        for rank, region_id in enumerate(order, 1):
            fused[region_id] = fused.get(region_id, 0.0) + 1.0 / (rrf_k + rank)
    routed = route_types(query)
    by_id = {region.id: region for region in pack.regions}
    candidates = sorted(
        fused,
        key=lambda region_id: (
            -(fused[region_id] + (0.001 if by_id[region_id].region_type in routed else 0.0)),
            region_id,
        ),
    )[:maxsim_k]
    rescored = []
    score_by_id = dict(zip(ids, zip(bm25_scores, dense_scores, strict=True), strict=True))
    for region_id in candidates:
        region = by_id[region_id]
        score = maxsim_scorer(checked_multi, region.multi, pack.multi_dim)
        if not math.isfinite(score):
            raise HybridQueryError("MaxSim scorer produced a non-finite score")
        bm25_score, dense_score = score_by_id[region_id]
        rescored.append(HybridHit(region_id, score, bm25_score, dense_score, score))
    hits = tuple(sorted(rescored, key=lambda hit: (-hit.score, hit.region_id))[:limit])
    prefiltered = tuple(
        sorted(
            fused,
            key=lambda region_id: (
                -(fused[region_id] + (0.001 if by_id[region_id].region_type in routed else 0.0)),
                region_id,
            ),
        )
    )
    return HybridResult(routed, len(fused), len(candidates), prefiltered, hits)

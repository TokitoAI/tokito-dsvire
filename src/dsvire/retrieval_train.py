"""SigLIP-MRL, ColQwen late-interaction, Light-merge, and binary rescoring math."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .eftri import REGION_TYPES

MRL_DIMS = (64, 512)
MAXSIM_K = 32


class RetrievalTrainError(ValueError):
    """A retrieval training tensor violated its finite, bounded contract."""


def _finite(values: Sequence[float], context: str) -> tuple[float, ...]:
    result: list[float] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number) or abs(number) > 1_000_000:
            raise RetrievalTrainError(f"{context} contains a non-finite or unbounded value")
        result.append(number)
    if not result:
        raise RetrievalTrainError(f"{context} is empty")
    return tuple(result)


def l2_normalize(vector: Sequence[float]) -> tuple[float, ...]:
    values = _finite(vector, "vector")
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 0:
        raise RetrievalTrainError("cannot normalize a zero vector")
    return tuple(item / norm for item in values)


def mrl_slices(vector: Sequence[float]) -> dict[int, tuple[float, ...]]:
    values = _finite(vector, "mrl")
    if len(values) < max(MRL_DIMS):
        raise RetrievalTrainError(f"MRL vector must contain at least {max(MRL_DIMS)} dimensions")
    return {dim: l2_normalize(values[:dim]) for dim in MRL_DIMS}


def info_nce(
    query: Sequence[float],
    positives: Sequence[Sequence[float]],
    negatives: Sequence[Sequence[float]],
    *,
    temperature: float = 0.07,
) -> float:
    if not 0.01 <= temperature <= 1.0:
        raise RetrievalTrainError("temperature must be within 0.01..=1.0")
    if not positives:
        raise RetrievalTrainError("InfoNCE requires at least one positive")
    query_vec = l2_normalize(query)
    logits: list[float] = []
    labels: list[int] = []
    for item in positives:
        other = l2_normalize(item)
        if len(other) != len(query_vec):
            raise RetrievalTrainError("positive dimension mismatch")
        logits.append(sum(a * b for a, b in zip(query_vec, other, strict=True)) / temperature)
        labels.append(1)
    for item in negatives:
        other = l2_normalize(item)
        if len(other) != len(query_vec):
            raise RetrievalTrainError("negative dimension mismatch")
        logits.append(sum(a * b for a, b in zip(query_vec, other, strict=True)) / temperature)
        labels.append(0)
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    loss = 0.0
    positive_count = 0
    for probability, label in zip((value / total for value in exps), labels, strict=True):
        if label:
            loss -= math.log(max(probability, 1e-12))
            positive_count += 1
    return loss / positive_count


def mrl_loss(
    query: Sequence[float],
    positive: Sequence[float],
    negatives: Sequence[Sequence[float]],
) -> float:
    query_slices = mrl_slices(query)
    positive_slices = mrl_slices(positive)
    losses = []
    for dim in MRL_DIMS:
        sliced_negatives = [mrl_slices(item)[dim] for item in negatives]
        losses.append(info_nce(query_slices[dim], (positive_slices[dim],), sliced_negatives))
    return sum(losses) / len(losses)


def maxsim(
    query_tokens: Sequence[Sequence[float]],
    document_tokens: Sequence[Sequence[float]],
    *,
    k: int = MAXSIM_K,
) -> float:
    if k < 1 or k > 4096:
        raise RetrievalTrainError("MaxSim k is outside 1..=4096")
    queries = [l2_normalize(token) for token in query_tokens[:k]]
    documents = [l2_normalize(token) for token in document_tokens[:k]]
    if not queries or not documents:
        raise RetrievalTrainError("MaxSim requires query and document tokens")
    dim = len(queries[0])
    total = 0.0
    for query in queries:
        if len(query) != dim:
            raise RetrievalTrainError("query token dimension mismatch")
        best = max(
            sum(a * b for a, b in zip(query, document, strict=True)) for document in documents
        )
        total += best
    return total / len(queries)


def light_merge(tokens: Sequence[Sequence[float]], *, keep: int) -> tuple[tuple[float, ...], ...]:
    if keep < 1:
        raise RetrievalTrainError("Light-merge must keep at least one token")
    current = [l2_normalize(token) for token in tokens]
    if not current:
        raise RetrievalTrainError("Light-merge received no tokens")
    while len(current) > keep:
        merged: list[tuple[float, ...]] = []
        index = 0
        while index < len(current):
            if index + 1 < len(current):
                left, right = current[index], current[index + 1]
                merged.append(
                    l2_normalize(tuple((a + b) / 2 for a, b in zip(left, right, strict=True)))
                )
                index += 2
            else:
                merged.append(current[index])
                index += 1
        current = merged
    return tuple(current)


def binary_quantize(vector: Sequence[float]) -> tuple[int, ...]:
    values = _finite(vector, "quantize")
    return tuple(1 if value >= 0 else 0 for value in values)


def hamming(left: Sequence[int], right: Sequence[int]) -> int:
    if len(left) != len(right):
        raise RetrievalTrainError("binary codes have different width")
    return sum(a != b for a, b in zip(left, right, strict=True))


def exact_rescore(
    query_tokens: Sequence[Sequence[float]],
    candidates: Sequence[Sequence[Sequence[float]]],
    *,
    keep: int,
) -> tuple[int, ...]:
    scores = [maxsim(query_tokens, document) for document in candidates]
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    return tuple(order[:keep])


def type_gate(region_type: str, query_types: Sequence[str]) -> bool:
    if region_type not in REGION_TYPES:
        raise RetrievalTrainError(f"unknown region type: {region_type}")
    allowed = set(query_types)
    if not allowed or not allowed.issubset(REGION_TYPES):
        raise RetrievalTrainError("query types must be a non-empty EFTRI subset")
    return region_type in allowed

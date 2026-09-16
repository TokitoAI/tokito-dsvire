"""EDA figure-type routing (EFTRI): soft top-2 with explicit abstention."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

REGION_TYPES = (
    "pinout",
    "package",
    "timing",
    "curve",
    "block",
    "app_circuit",
    "table",
    "other",
)
TYPE_INDEX = {name: index for index, name in enumerate(REGION_TYPES)}
LAYOUT_TO_TYPES = {
    "figure": ("pinout", "package", "timing", "curve", "block", "app_circuit", "other"),
    "table": ("table", "other"),
    "other": ("other",),
}


class EftriError(ValueError):
    """Type routing logits or labels violated the EFTRI contract."""


@dataclass(frozen=True)
class TypeDecision:
    primary: str
    secondary: str | None
    confidence: float
    margin: float
    abstained: bool


def softmax(logits: Sequence[float]) -> tuple[float, ...]:
    if len(logits) != len(REGION_TYPES):
        raise EftriError(f"EFTRI expects {len(REGION_TYPES)} logits")
    if any(not math.isfinite(value) for value in logits):
        raise EftriError("EFTRI logits must be finite")
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    if total <= 0:
        raise EftriError("EFTRI softmax denominator is not positive")
    return tuple(value / total for value in exps)


def route(
    logits: Sequence[float],
    *,
    layout_label: str,
    minimum_confidence: float = 0.35,
    minimum_margin: float = 0.05,
) -> TypeDecision:
    if not 0.2 <= minimum_confidence <= 0.9:
        raise EftriError("EFTRI confidence floor must be within 0.2..=0.9")
    allowed = LAYOUT_TO_TYPES.get(layout_label)
    if allowed is None:
        raise EftriError(f"unsupported layout label for EFTRI: {layout_label}")
    probabilities = list(softmax(logits))
    for name, index in TYPE_INDEX.items():
        if name not in allowed:
            probabilities[index] = 0.0
    total = sum(probabilities)
    if total <= 0:
        return TypeDecision("other", None, 0.0, 0.0, True)
    probabilities = [value / total for value in probabilities]
    ranked = sorted(
        ((prob, name) for name, prob in zip(REGION_TYPES, probabilities, strict=True)),
        reverse=True,
    )
    top_prob, primary = ranked[0]
    second_prob, secondary = ranked[1]
    margin = top_prob - second_prob
    abstained = top_prob < minimum_confidence or margin < minimum_margin
    return TypeDecision(
        primary=primary if not abstained else "other",
        secondary=None if abstained or second_prob < 0.15 else secondary,
        confidence=round(top_prob, 6),
        margin=round(margin, 6),
        abstained=abstained,
    )


def hard_negatives(primary: str) -> tuple[str, ...]:
    if primary not in TYPE_INDEX:
        raise EftriError(f"unknown region type: {primary}")
    return tuple(name for name in REGION_TYPES if name != primary)


def cross_entropy(logits: Sequence[float], label: str) -> float:
    if label not in TYPE_INDEX:
        raise EftriError(f"unknown supervision label: {label}")
    probabilities = softmax(logits)
    probability = probabilities[TYPE_INDEX[label]]
    if probability <= 0:
        return 1e6
    return -math.log(probability)


def assert_no_eval_types(labels: Mapping[str, str], sealed_document_hashes: set[str]) -> None:
    leaked = sorted(doc for doc in labels if doc in sealed_document_hashes)
    if leaked:
        raise EftriError(f"EFTRI labels include sealed evaluation documents: {leaked[:8]}")

"""Technical Bible §8 / §9.4 release gates. No waiver object can flip a failed gate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

GATE_VERSION = "dsvire.ablation-gates.v1"
REQUIRED_BASELINES = (
    "bm25_structured_text",
    "dense_text_rag",
    "siglip_pages",
    "dse_page_vector",
    "colqwen2_full_page",
    "colqwen2_light_merge",
    "layout_crop_siglip",
    "lgpc",
    "lgpc_eftri",
)
SLO = {
    "query_p95_hot_ms_maximum": 800.0,
    "figure_r_at_5_vs_full_page_minimum_delta": -0.01,
    "figure_r_at_5_vs_text_rag_minimum_delta": 0.15,
    "index_pages_per_second_per_gpu_minimum": 2.0,
    "pack_vs_full_page_ratio_maximum": 0.15,
    "verified_wrong_figure_rate_maximum": 0.02,
    "ndcg_regression_maximum": 0.02,
}


class AblationGateError(ValueError):
    """Ablation evidence is incomplete, retuned, or below a frozen SLO."""


def _number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AblationGateError(f"{context} must be a number")
    number = float(value)
    if number != number or abs(number) == float("inf"):
        raise AblationGateError(f"{context} must be finite")
    return number


def evaluate_ablation_gates(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if evidence.get("schema_version") != GATE_VERSION:
        raise AblationGateError("unsupported ablation evidence schema")
    if evidence.get("waiver"):
        raise AblationGateError("waivers cannot replace a frozen SLO gate")
    baselines = evidence.get("baselines")
    if not isinstance(baselines, Mapping):
        raise AblationGateError("baselines must be an object")
    missing = [name for name in REQUIRED_BASELINES if name not in baselines]
    if missing:
        raise AblationGateError(f"missing required baselines: {missing}")
    candidate = evidence.get("candidate")
    if not isinstance(candidate, Mapping):
        raise AblationGateError("candidate metrics are required")
    full_page = (
        _number(baselines["colqwen2_full_page"].get("r_at_5"), "full_page.r_at_5")
        if isinstance(baselines["colqwen2_full_page"], Mapping)
        else None
    )
    text_rag = (
        _number(baselines["dense_text_rag"].get("r_at_5"), "text_rag.r_at_5")
        if isinstance(baselines["dense_text_rag"], Mapping)
        else None
    )
    if full_page is None or text_rag is None:
        raise AblationGateError("full-page ColQwen2 and text-RAG must report r_at_5")
    candidate_r = _number(candidate.get("r_at_5"), "candidate.r_at_5")
    p95 = _number(candidate.get("query_p95_hot_ms"), "candidate.query_p95_hot_ms")
    throughput = _number(candidate.get("index_pages_per_second_per_gpu"), "candidate.throughput")
    pack_ratio = _number(candidate.get("pack_vs_full_page_ratio"), "candidate.pack_ratio")
    wrong_figure = _number(candidate.get("verified_wrong_figure_rate"), "candidate.wrong_figure")
    ndcg_delta = _number(candidate.get("ndcg_delta_vs_previous"), "candidate.ndcg_delta")
    failures: list[str] = []
    if candidate_r < full_page + SLO["figure_r_at_5_vs_full_page_minimum_delta"]:
        failures.append("figure_r_at_5_vs_full_page")
    if candidate_r < text_rag + SLO["figure_r_at_5_vs_text_rag_minimum_delta"]:
        failures.append("figure_r_at_5_vs_text_rag")
    if p95 > SLO["query_p95_hot_ms_maximum"]:
        failures.append("query_p95_hot_ms")
    if throughput < SLO["index_pages_per_second_per_gpu_minimum"]:
        failures.append("index_throughput")
    if pack_ratio > SLO["pack_vs_full_page_ratio_maximum"]:
        failures.append("pack_size")
    if wrong_figure > SLO["verified_wrong_figure_rate_maximum"]:
        failures.append("wrong_figure_rate")
    if ndcg_delta < -SLO["ndcg_regression_maximum"]:
        failures.append("ndcg_regression")
    return {
        "schema_version": GATE_VERSION,
        "passed": not failures,
        "failures": failures,
        "slo": SLO,
        "candidate_r_at_5": candidate_r,
        "full_page_r_at_5": full_page,
        "text_rag_r_at_5": text_rag,
    }

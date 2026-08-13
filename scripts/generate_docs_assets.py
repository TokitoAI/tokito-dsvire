"""Generate public, source-free documentation examples from committed evidence."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from dsvire.corpus_coverage import audit_corpus_coverage, load_coverage_policy, load_query_registry
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT
EVIDENCE = ROOT / "fixtures/evidence/tps5430ddar.json"
BENCHMARK = ROOT / "evaluation/results/multivendor-development-2026-08-12.json"
SERVICE_LOAD = ROOT / "evaluation/results/service-load-linux-2026-08-12.json"
VISUAL_REGISTRY = ROOT / "evaluation/visual_registry.v1.json"
COVERAGE_POLICY = ROOT / "evaluation/corpus_coverage_policy.v1.json"
QUERY_REGISTRY = ROOT / "evaluation/query_registry.v2.json"
QUERY_RANKING = ROOT / "examples/query-ranking-canary.json"
FULL_CORPUS_TEXT = ROOT / "evaluation/results/full-corpus-text-development-2026-08-13.json"
FULL_CORPUS_OPENCLIP = ROOT / "evaluation/results/full-corpus-openclip-development-2026-08-13.json"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _fmt_mib(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


def _example(evidence: dict[str, Any]) -> dict[str, Any]:
    datasheet = evidence["datasheet"]
    regions = evidence["regions"]
    return {
        "schema_version": "dsvire.public-example.v1",
        "part": {
            "manufacturer": datasheet["manufacturer"],
            "mpn": datasheet["mpn"],
            "package": datasheet["package"],
            "datasheet_sha256": datasheet["content_sha256"],
        },
        "identity_verification": evidence["identity_verification"],
        "evidence": [
            {
                "type": region["type"],
                "page": region["page"],
                "bbox_norm": region["bbox_norm"],
                "caption": region.get("caption"),
                "content_hash": region["content_hash"],
                "verification": region["verification"],
            }
            for region in regions
        ],
        "publication_eligible": False,
        "calibrated_probability": None,
        "publication_blocker": (
            "fixture regions use text_layout_heuristic with heuristic_evidence_strength; "
            "the Technical Bible permits automated publication only for an allowed, "
            "held-out-calibrated evidence_gated_visual policy"
        ),
    }


def _evidence_svg(example: dict[str, Any]) -> str:
    part = example["part"]
    regions = example["evidence"]
    colors = {"pinout": "#16d6b3", "table": "#62a6ff", "package": "#a78bfa"}
    cards = []
    for index, region in enumerate(regions):
        y = 278 + index * 132
        color = colors.get(region["type"], "#f2b84b")
        bbox = ", ".join(f"{value:.3f}" for value in region["bbox_norm"])
        caption = html.escape(str(region.get("caption") or ""))
        digest = html.escape(str(region["content_hash"]).removeprefix("sha256:")[:16])
        cards.append(
            f'<rect x="54" y="{y}" width="1092" height="108" rx="16" fill="#121720" stroke="#293140"/>'
            f'<rect x="54" y="{y}" width="8" height="108" rx="4" fill="{color}"/>'
            f'<text x="84" y="{y + 32}" class="type" fill="{color}">{html.escape(region["type"].upper())}</text>'
            f'<text x="218" y="{y + 32}" class="caption">{caption}</text>'
            f'<text x="84" y="{y + 65}" class="meta">page {region["page"]} · bbox [{bbox}]</text>'
            f'<text x="84" y="{y + 89}" class="mono">crop sha256 {digest}…</text>'
            f'<text x="900" y="{y + 70}" class="score">{region["verification"]["score"]:.2f}</text>'
            f'<text x="900" y="{y + 91}" class="tiny">heuristic strength</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760" role="img" aria-labelledby="title desc">\n'
        '  <title id="title">DS-ViRe source-free evidence bundle example</title>\n'
        '  <desc id="desc">Three region-level evidence records with page, bounding box, content hash, and explicitly heuristic verification semantics.</desc>\n'
        '  <rect width="1200" height="760" rx="28" fill="#090b10"/>\n'
        "  <style>.title{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}.sub{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}.label{font:600 14px Inter,Segoe UI,sans-serif;fill:#8d96a8}.value{font:700 20px Inter,Segoe UI,sans-serif;fill:#f4f7fb}.type{font:700 15px Inter,Segoe UI,sans-serif}.caption{font:600 16px Inter,Segoe UI,sans-serif;fill:#f4f7fb}.meta{font:15px Inter,Segoe UI,sans-serif;fill:#b5bfce}.mono{font:14px ui-monospace,Consolas,monospace;fill:#778398}.score{font:700 28px ui-monospace,Consolas,monospace;fill:#f4f7fb}.tiny{font:13px Inter,Segoe UI,sans-serif;fill:#8d96a8}</style>\n"
        '  <text x="54" y="65" class="title">Evidence bundle · not a PDF dump</text>\n'
        '  <text x="54" y="101" class="sub">Every result is a typed region with page, normalized geometry, hash, and score semantics.</text>\n'
        '  <rect x="54" y="132" width="1092" height="112" rx="18" fill="#121720" stroke="#293140"/>\n'
        f'  <text x="82" y="164" class="label">EXACT PART IDENTITY</text><text x="82" y="198" class="value">{html.escape(part["manufacturer"])} · {html.escape(part["mpn"])} · {html.escape(part["package"])}</text>\n'
        f'  <text x="82" y="224" class="mono">datasheet sha256 {html.escape(part["datasheet_sha256"][:32])}…</text>\n'
        + "  "
        + "\n  ".join(cards)
        + '\n  <rect x="54" y="686" width="1092" height="42" rx="12" fill="#2a1c13" stroke="#7c4a22"/><text x="76" y="713" class="caption" fill="#f3ba76">ABSTAIN: heuristic_evidence_strength is not calibrated_probability and cannot authorize publication.</text>\n'
        "</svg>\n"
    )


def _benchmark_svg(benchmark: dict[str, Any]) -> str:
    comparators = benchmark["comparators"]
    labels = ["positive", "wrong_package", "wrong_variant", "wrong_view", "wrong_figure"]
    display = {
        "positive": "Positive",
        "wrong_package": "Wrong package",
        "wrong_variant": "Wrong variant",
        "wrong_view": "Wrong view",
        "wrong_figure": "Wrong figure",
    }
    colors = ("#16d6b3", "#8b7cf6")
    rows = []
    for index, label in enumerate(labels):
        y = 200 + index * 78
        values = [float(item["mean_similarity_by_label"][label]) for item in comparators]
        rows.append(f'<text x="64" y="{y + 26}" class="row">{display[label]}</text>')
        for comparator_index, value in enumerate(values):
            by = y + comparator_index * 27
            rows.append(f'<rect x="250" y="{by}" width="560" height="20" rx="10" fill="#202631"/>')
            rows.append(
                f'<rect x="250" y="{by}" width="{max(1, round(value * 560))}" height="20" rx="10" fill="{colors[comparator_index]}"/>'
            )
        rows.append(
            f'<text x="830" y="{y + 25}" class="mono">{values[0]:.3f} / {values[1]:.3f}</text>'
        )
    first, second = comparators
    scope = benchmark["scope"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760" role="img" aria-labelledby="title desc">
  <title id="title">DS-ViRe multi-vendor development benchmark</title>
  <desc id="desc">Mean similarity by label and operational measurements derived from the committed benchmark JSON.</desc>
  <rect width="1200" height="760" rx="28" fill="#090b10"/>
  <style>.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.sub{{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.legend{{font:16px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.row{{font:17px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.mono{{font:15px ui-monospace,Consolas,monospace;fill:#f4f7fb}}.metric{{font:700 22px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.label{{font:14px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#697386}}</style>
  <text x="64" y="70" class="title">Multi-vendor visual benchmark</text>
  <text x="64" y="108" class="sub">{scope["documents"]} official datasheets · {scope["cases"]} adversarial cases · {scope["review_status"]} {scope["split"]} split</text>
  <circle cx="70" cy="151" r="7" fill="{colors[0]}"/><text x="88" y="158" class="legend">Text layout</text>
  <circle cx="230" cy="151" r="7" fill="{colors[1]}"/><text x="248" y="158" class="legend">RapidOCR</text>
  {"".join(rows)}
  <rect x="48" y="606" width="1104" height="106" rx="18" fill="#121720" stroke="#293140"/>
  <text x="76" y="638" class="label">TEXT LAYOUT</text><text x="76" y="677" class="metric">{first["elapsed_seconds"]:.3f} s · {first["documents_per_second"]:.2f} docs/s · {_fmt_mib(first["peak_rss_bytes"])}</text>
  <text x="626" y="638" class="label">RAPIDOCR · CPU</text><text x="626" y="677" class="metric">{second["elapsed_seconds"]:.2f} s · {second["documents_per_second"]:.3f} docs/s · {_fmt_mib(second["peak_rss_bytes"])}</text>
  <text x="64" y="741" class="foot">Similarity, not probability · no threshold fitted · not eligible for publication policy · source: evaluation/results/multivendor-development-2026-08-12.json</text>
</svg>
'''


def _service_load_svg(result: dict[str, Any]) -> str:
    values = result["results"]
    cold = values["cold"]
    warm = values["warm"]
    overload = values["overload"]
    rss = _fmt_mib(values["peak_process_tree_rss_bytes"])
    bars = (
        ("Cold PDF to evidence p95", float(cold["p95_ms"]), "#62a6ff"),
        ("Warm/cache phase p95", float(warm["p95_ms"]), "#16d6b3"),
        ("Warm steady max", float(warm["steady_cached_max_ms"]), "#a78bfa"),
        ("Overload rejection max", float(overload["rejection_max_ms"]), "#f2b84b"),
    )
    rows = []
    scale = 720 / max(value for _, value, _ in bars)
    for index, (label, value, color) in enumerate(bars):
        y = 208 + index * 80
        rows.append(f'<text x="64" y="{y + 21}" class="row">{label}</text>')
        rows.append(f'<rect x="350" y="{y}" width="720" height="26" rx="13" fill="#202631"/>')
        rows.append(
            f'<rect x="350" y="{y}" width="{round(value * scale)}" height="26" rx="13" fill="{color}"/>'
        )
        rows.append(f'<text x="1090" y="{y + 21}" class="mono">{value:.1f} ms</text>')
    run = result["source"]["workflow_run"]
    commit = result["source"]["commit"][:8]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760" role="img" aria-labelledby="title desc">
  <title id="title">DS-ViRe authenticated service load evidence</title>
  <desc id="desc">Latency, bounded overload, memory, and cleanup measurements from a generated-PDF Linux CI run.</desc>
  <rect width="1200" height="760" rx="28" fill="#090b10"/>
  <style>.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.sub{{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.row{{font:17px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.mono{{font:15px ui-monospace,Consolas,monospace;fill:#f4f7fb}}.metric{{font:700 24px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.label{{font:14px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#697386}}</style>
  <text x="64" y="70" class="title">Authenticated service boundary · Linux CI</text>
  <text x="64" y="108" class="sub">Real Uvicorn HTTP → admission → spawned worker → persistent pack · generated PDFs only</text>
  <text x="64" y="154" class="label">RUN {run} · COMMIT {commit} · 1 WORKER · 100 MS ADMISSION WINDOW</text>
  {"".join(rows)}
  <rect x="48" y="558" width="1104" height="120" rx="18" fill="#121720" stroke="#293140"/>
  <text x="76" y="590" class="label">BOUNDARY OUTCOMES</text>
  <text x="76" y="630" class="metric">7 success · 5 bounded 503 · 0 unexpected</text>
  <text x="640" y="590" class="label">RESOURCE / DURABILITY</text>
  <text x="640" y="630" class="metric">{rss} peak RSS · 4 packs · 0 residue</text>
  <text x="64" y="720" class="foot">Indexing evidence, not the future hot-pack MaxSim query SLO · single 4-vCPU CI runner · 12 requests · no E2E extrapolation</text>
</svg>
"""


def _coverage_svg(result: dict[str, Any]) -> str:
    achieved = result["achieved"]
    targets = result["targets"]
    reviews = result["review"]
    strata = result["category_strata_documents"]
    max_stratum = max(strata.values())
    rows = []
    for index, (name, count) in enumerate(strata.items()):
        y = 337 + index * 43
        width = round(400 * count / max_stratum)
        rows.append(f'<text x="68" y="{y + 18}" class="row">{html.escape(name.upper())}</text>')
        rows.append(f'<rect x="196" y="{y}" width="400" height="22" rx="11" fill="#202631"/>')
        rows.append(f'<rect x="196" y="{y}" width="{width}" height="22" rx="11" fill="#62a6ff"/>')
        rows.append(f'<text x="612" y="{y + 18}" class="mono">{count}</text>')
    document_width = round(1000 * achieved["documents"] / targets["documents"])
    query_width = round(1000 * achieved["explicit_queries"] / targets["queries"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760" role="img" aria-labelledby="title desc">
  <title id="title">DS-ViRe corpus coverage against Technical Bible targets</title>
  <desc id="desc">Source-free coverage ledger showing documents, explicit queries, categories, manufacturers, category strata, and review provenance.</desc>
  <rect width="1200" height="760" rx="28" fill="#090b10"/>
  <style>.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.sub{{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.label{{font:14px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.metric{{font:700 28px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.row{{font:600 14px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.mono{{font:15px ui-monospace,Consolas,monospace;fill:#f4f7fb}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#697386}}</style>
  <text x="64" y="68" class="title">Corpus coverage · measured, not implied</text>
  <text x="64" y="105" class="sub">Technical Bible target: 500 documents · 2,000 explicit benchmark queries</text>
  <text x="64" y="151" class="label">DOCUMENTS</text><text x="64" y="187" class="metric">{achieved["documents"]} / {targets["documents"]}</text>
  <rect x="64" y="207" width="1000" height="22" rx="11" fill="#202631"/><rect x="64" y="207" width="{document_width}" height="22" rx="11" fill="#16d6b3"/>
  <text x="64" y="261" class="label">EXPLICIT NATURAL-LANGUAGE QUERIES</text><text x="64" y="297" class="metric">{achieved["explicit_queries"]} / {targets["queries"]}</text>
  <rect x="64" y="309" width="1000" height="12" rx="6" fill="#202631"/><rect x="64" y="309" width="{query_width}" height="12" rx="6" fill="#f2b84b"/>
  {"".join(rows)}
  <rect x="706" y="349" width="430" height="230" rx="18" fill="#121720" stroke="#293140"/>
  <text x="736" y="385" class="label">SOURCE-FREE REGISTRY</text><text x="736" y="427" class="metric">{achieved["annotated_cases"]} cases</text>
  <text x="736" y="469" class="row">{achieved["manufacturers"]} manufacturers · {achieved["categories"]} categories</text>
  <text x="736" y="510" class="row">{reviews["owner_authorized_agent_documents"]} agent-reviewed documents</text>
  <text x="736" y="546" class="row">{reviews["independent_human_documents"]} independent-human-reviewed documents</text>
  <rect x="48" y="650" width="1104" height="58" rx="14" fill="#2a1c13" stroke="#7c4a22"/>
  <text x="72" y="685" class="row">Annotation cases are not queries. Coverage is not accuracy, representativeness, independent review, or legal approval.</text>
  <text x="64" y="740" class="foot">Generated from evaluation/visual_registry.v1.json + corpus_coverage_policy.v1.json · no vendor PDF bytes</text>
</svg>
'''


def _query_ranking_svg(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    rows = (
        ("nDCG@5", metrics["ndcg_at_5"], "#16d6b3"),
        ("R@5", metrics["recall_at_5"], "#62a6ff"),
        ("mAP", metrics["map"], "#a78bfa"),
        ("MRR", metrics["mrr"], "#f2b84b"),
    )
    bars = []
    for index, (label, value, color) in enumerate(rows):
        y = 220 + index * 78
        bars.append(f'<text x="72" y="{y + 24}" class="row">{label}</text>')
        bars.append(f'<rect x="220" y="{y}" width="760" height="28" rx="14" fill="#202631"/>')
        bars.append(
            f'<rect x="220" y="{y}" width="{round(760 * value)}" height="28" rx="14" fill="{color}"/>'
        )
        bars.append(f'<text x="1010" y="{y + 23}" class="mono">{value:.3f}</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700" role="img" aria-labelledby="title desc">
  <title id="title">DS-ViRe query-ranking contract canary</title>
  <desc id="desc">Closed judged-pool metric canary generated from 90 deterministic development queries.</desc>
  <rect width="1200" height="700" rx="28" fill="#090b10"/>
  <style>.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.sub{{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.row{{font:700 18px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.mono{{font:17px ui-monospace,Consolas,monospace;fill:#f4f7fb}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#697386}}</style>
  <text x="64" y="70" class="title">Query-ranking contract canary</text>
  <text x="64" y="108" class="sub">{metrics["queries"]} deterministic development queries - closed judged pool - byte-stable evaluator</text>
  <rect x="64" y="138" width="1072" height="48" rx="12" fill="#2a1c13" stroke="#7c4a22"/>
  <text x="86" y="169" class="row">NOT retrieval accuracy: relevance-first ordering deliberately exercises metric plumbing.</text>
  {"".join(bars)}
  <text x="64" y="585" class="row">{metrics["queries_with_hard_negative_at_5"]} / {metrics["queries"]} queries expose judged hard negatives in top 5</text>
  <text x="64" y="650" class="foot">No vendor bytes - no full-corpus retrieval - no held-out queries - cannot authorize publication</text>
</svg>
"""


def _full_corpus_text_svg(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    by_type = result["by_query_type"]
    rows = []
    colors = {"pinout": "#f2b84b", "table": "#16d6b3", "package": "#62a6ff"}
    for index, name in enumerate(("pinout", "table", "package")):
        y = 292 + index * 78
        value = float(by_type[name]["ndcg_at_5"])
        rows.append(f'<text x="74" y="{y + 24}" class="row">{name.upper()}</text>')
        rows.append(f'<rect x="240" y="{y}" width="700" height="28" rx="14" fill="#202631"/>')
        rows.append(
            f'<rect x="240" y="{y}" width="{round(700 * value)}" height="28" rx="14" fill="{colors[name]}"/>'
        )
        rows.append(f'<text x="974" y="{y + 23}" class="mono">{value:.3f}</text>')
    scope = result["scope"]
    runtime = result["runtime"]
    ranking = result["ranking_sha256"][:16]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700" role="img" aria-labelledby="title desc">
  <title id="title">DS-ViRe full-corpus text baseline development measurement</title>
  <desc id="desc">Identity-assisted text and layout baseline ranked all registered development candidates for every development query.</desc>
  <rect width="1200" height="700" rx="28" fill="#090b10"/>
  <style>.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.sub{{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.metric{{font:700 30px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.label{{font:14px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.row{{font:700 17px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.mono{{font:16px ui-monospace,Consolas,monospace;fill:#f4f7fb}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#697386}}</style>
  <text x="64" y="68" class="title">Full registered-corpus ranking - development baseline</text>
  <text x="64" y="105" class="sub">Identity-assisted text/layout retrieval; ground-truth labels are never read by the scorer.</text>
  <rect x="64" y="134" width="1072" height="72" rx="16" fill="#2a1c13" stroke="#7c4a22"/>
  <text x="88" y="165" class="row">DEVELOPMENT ONLY - DETERMINISTIC-TEMPLATE QUERIES - NOT HELD-OUT ACCURACY</text>
  <text x="88" y="190" class="foot">Complete registered candidate universe, not every unannotated figure in each PDF.</text>
  <text x="72" y="253" class="label">NDCG@5 BY QUERY INTENT</text>
  {"".join(rows)}
  <rect x="58" y="540" width="1084" height="92" rx="18" fill="#121720" stroke="#293140"/>
  <text x="84" y="571" class="label">SCOPE</text><text x="84" y="606" class="metric">{scope["documents"]} docs - {scope["queries"]} queries - {scope["candidate_cases"]} candidates</text>
  <text x="680" y="571" class="label">AGGREGATE / OPERATIONS</text><text x="680" y="606" class="metric">{metrics["ndcg_at_5"]:.3f} nDCG@5 - {runtime["total_seconds"]:.2f} s</text>
  <text x="64" y="670" class="foot">{scope["ranked_pairs"]:,} scored pairs - 100% coverage - ranking sha256 {ranking}... - zero external cost</text>
</svg>
"""


def _retrieval_comparison_svg(text: dict[str, Any], visual: dict[str, Any]) -> str:
    metrics = ("ndcg_at_5", "recall_at_5", "map", "mrr")
    labels = {"ndcg_at_5": "nDCG@5", "recall_at_5": "R@5", "map": "mAP", "mrr": "MRR"}
    rows = []
    for index, name in enumerate(metrics):
        y = 244 + index * 76
        assisted = float(text["metrics"][name])
        unscoped = float(visual["metrics"][name])
        rows.extend(
            [
                f'<text x="64" y="{y + 25}" class="row">{labels[name]}</text>',
                f'<rect x="220" y="{y}" width="720" height="22" rx="11" fill="#202631"/>',
                f'<rect x="220" y="{y}" width="{round(720 * assisted)}" height="22" rx="11" fill="#16d6b3"/>',
                f'<rect x="220" y="{y + 29}" width="720" height="22" rx="11" fill="#202631"/>',
                f'<rect x="220" y="{y + 29}" width="{round(720 * unscoped)}" height="22" rx="11" fill="#a78bfa"/>',
                f'<text x="972" y="{y + 18}" class="mono">{assisted:.3f}</text>',
                f'<text x="972" y="{y + 47}" class="mono">{unscoped:.3f}</text>',
            ]
        )
    scope = visual["scope"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700" role="img" aria-labelledby="title desc">
  <title id="title">Identity-assisted versus unscoped visual retrieval</title>
  <desc id="desc">Development comparison over the same complete registered query and candidate universe.</desc>
  <rect width="1200" height="700" rx="28" fill="#090b10"/>
  <style>.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f4f7fb}}.sub{{font:18px Inter,Segoe UI,sans-serif;fill:#8d96a8}}.legend{{font:16px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.row{{font:700 18px Inter,Segoe UI,sans-serif;fill:#c8d0dc}}.mono{{font:16px ui-monospace,Consolas,monospace;fill:#f4f7fb}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#697386}}</style>
  <text x="64" y="68" class="title">Same corpus, radically different information boundary</text>
  <text x="64" y="105" class="sub">{scope["queries"]} queries x {scope["candidate_cases"]} registered crops = {scope["ranked_pairs"]:,} scored pairs</text>
  <circle cx="72" cy="151" r="7" fill="#16d6b3"/><text x="90" y="157" class="legend">Identity-assisted text/layout</text>
  <circle cx="338" cy="151" r="7" fill="#a78bfa"/><text x="356" y="157" class="legend">Unscoped OpenCLIP pixels</text>
  <rect x="64" y="177" width="1072" height="42" rx="12" fill="#2a1c13" stroke="#7c4a22"/><text x="84" y="204" class="row">DEVELOPMENT ONLY - NOT HELD-OUT ACCURACY - NEITHER RESULT AUTHORIZES PUBLICATION</text>
  {"".join(rows)}
  <text x="64" y="628" class="row">Unscoped nDCG@5 by intent: pinout {visual["by_query_type"]["pinout"]["ndcg_at_5"]:.3f} - package {visual["by_query_type"]["package"]["ndcg_at_5"]:.3f} - table {visual["by_query_type"]["table"]["ndcg_at_5"]:.3f}</text>
  <text x="64" y="670" class="foot">OpenCLIP scorer sees only raw query text and rendered crop pixels; no identity, package, intent, document metadata, or labels.</text>
</svg>
"""


def generate(output_root: Path) -> None:
    evidence = _read(EVIDENCE)
    benchmark = _read(BENCHMARK)
    service_load = _read(SERVICE_LOAD)
    query_ranking = _read(QUERY_RANKING)
    full_corpus_text = _read(FULL_CORPUS_TEXT)
    full_corpus_openclip = _read(FULL_CORPUS_OPENCLIP)
    visual_registry = load_visual_registry_data(_read(VISUAL_REGISTRY))
    coverage = audit_corpus_coverage(
        visual_registry,
        load_coverage_policy(_read(COVERAGE_POLICY)),
        load_query_registry(_read(QUERY_REGISTRY), visual_registry),
    )
    example = _example(evidence)
    _write(
        output_root / "examples/tps5430ddar-evidence-summary.json",
        json.dumps(example, indent=2, ensure_ascii=False) + "\n",
    )
    _write(output_root / "docs/assets/evidence-bundle-example.svg", _evidence_svg(example))
    _write(
        output_root / "docs/assets/multivendor-development-benchmark.svg",
        _benchmark_svg(benchmark),
    )
    _write(output_root / "docs/assets/service-load-evidence.svg", _service_load_svg(service_load))
    _write(
        output_root / "examples/corpus-coverage.json",
        json.dumps(coverage, indent=2, ensure_ascii=False) + "\n",
    )
    _write(output_root / "docs/assets/corpus-coverage.svg", _coverage_svg(coverage))
    _write(
        output_root / "docs/assets/query-ranking-canary.svg",
        _query_ranking_svg(query_ranking),
    )
    _write(
        output_root / "docs/assets/full-corpus-text-development.svg",
        _full_corpus_text_svg(full_corpus_text),
    )
    _write(
        output_root / "docs/assets/full-corpus-retrieval-comparison.svg",
        _retrieval_comparison_svg(full_corpus_text, full_corpus_openclip),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

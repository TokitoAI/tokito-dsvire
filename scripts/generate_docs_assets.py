"""Generate public, source-free documentation examples from committed evidence."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT
EVIDENCE = ROOT / "fixtures/evidence/tps5430ddar.json"
BENCHMARK = ROOT / "evaluation/results/multivendor-development-2026-08-12.json"
SERVICE_LOAD = ROOT / "evaluation/results/service-load-linux-2026-08-12.json"


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


def generate(output_root: Path) -> None:
    evidence = _read(EVIDENCE)
    benchmark = _read(BENCHMARK)
    service_load = _read(SERVICE_LOAD)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

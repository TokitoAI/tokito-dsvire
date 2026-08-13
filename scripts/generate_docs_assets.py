"""Generate the compact public documentation visuals from committed evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT
COLSMOL = ROOT / "evaluation/results/full-corpus-colsmol-development-2026-08-13.json"
TEXT_BASELINE = ROOT / "evaluation/results/full-corpus-text-pdfium-development-2026-08-13.json"
OPENCLIP = ROOT / "evaluation/results/full-corpus-openclip-pdfium-development-2026-08-13.json"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _benchmark(
    text_result: dict[str, Any],
    openclip_result: dict[str, Any],
    colsmol_result: dict[str, Any],
) -> str:
    series = (
        ("Lexical + layout", text_result["metrics"], "#8d9aad"),
        ("OpenCLIP", openclip_result["metrics"], "#7067f0"),
        ("ColSmol-256M", colsmol_result["metrics"], "#18cdb2"),
    )
    rows: list[str] = []
    for index, (name, metrics, color) in enumerate(series):
        y = 280 + index * 112
        ndcg = float(metrics["ndcg_at_5"])
        recall = float(metrics["recall_at_5"])
        rows.extend(
            (
                f'<text x="76" y="{y + 23}" class="row">{name}</text>',
                f'<rect x="300" y="{y}" width="610" height="28" rx="14" fill="#202937"/>',
                f'<rect x="300" y="{y}" width="{round(610 * ndcg)}" height="28" rx="14" fill="{color}"/>',
                f'<text x="940" y="{y + 22}" class="mono">{ndcg:.3f}</text>',
                f'<text x="1080" y="{y + 22}" class="mono">{recall:.3f}</text>',
            )
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="680" viewBox="0 0 1200 680" role="img" aria-labelledby="title desc"><title id="title">DS-ViRe model comparison</title><desc id="desc">Comparison of lexical and layout retrieval, OpenCLIP, and ColSmol on the same 90-query development corpus.</desc><rect width="1200" height="680" rx="28" fill="#080b11"/><style>.eyebrow{{font:700 14px Inter,Segoe UI,sans-serif;letter-spacing:2px;fill:#18cdb2}}.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f5f7fb}}.sub{{font:17px Inter,Segoe UI,sans-serif;fill:#8d9aad}}.label{{font:13px Inter,Segoe UI,sans-serif;fill:#7f8ca1}}.row{{font:700 17px Inter,Segoe UI,sans-serif;fill:#d5dce7}}.mono{{font:16px ui-monospace,Consolas,monospace;fill:#f5f7fb}}.foot{{font:14px Inter,Segoe UI,sans-serif;fill:#748095}}</style><text x="64" y="64" class="eyebrow">MODEL COMPARISON</text><text x="64" y="108" class="title">Retrieval quality on one frozen candidate universe</text><text x="64" y="142" class="sub">30 documents · 90 queries · 209 crops · identical relevance judgments</text><line x1="300" y1="211" x2="910" y2="211" stroke="#263346"/><text x="76" y="218" class="label">SYSTEM</text><text x="300" y="218" class="label">NDCG@5</text><text x="940" y="218" class="label">SCORE</text><text x="1080" y="218" class="label">RECALL@5</text>{"".join(rows)}<text x="64" y="622" class="foot">The lexical baseline benefits from literal part-number and label overlap; neural models test visual-semantic retrieval.</text><text x="64" y="648" class="foot">Development split. Reproduce with the committed manifests, rankings, and result JSON under evaluation/.</text></svg>
"""


def generate(output_root: Path) -> None:
    _write(
        output_root / "docs/assets/benchmark-overview.svg",
        _benchmark(_read(TEXT_BASELINE), _read(OPENCLIP), _read(COLSMOL)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

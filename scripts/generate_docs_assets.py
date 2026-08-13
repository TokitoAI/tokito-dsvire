"""Generate the compact public documentation visuals from committed evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT
SPEC = ROOT / "fixtures/acceptance/tps5430ddar.spec.json"
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


def _symbol_pins(spec: dict[str, Any]) -> str:
    pins = spec["pins"]
    output: list[str] = []
    for index, pin in enumerate(pins[:4]):
        y = 372 + index * 62
        output.extend(
            (
                f'<line x1="905" y1="{y}" x2="975" y2="{y}" class="pin"/>',
                f'<text x="892" y="{y + 6}" text-anchor="end" class="pin-name">{pin["name"]}</text>',
                f'<text x="940" y="{y - 9}" text-anchor="middle" class="pin-number">{pin["number"]}</text>',
            )
        )
    for index, pin in enumerate(pins[4:]):
        y = 558 - index * 62
        output.extend(
            (
                f'<line x1="1235" y1="{y}" x2="1305" y2="{y}" class="pin"/>',
                f'<text x="1318" y="{y + 6}" class="pin-name">{pin["name"]}</text>',
                f'<text x="1270" y="{y - 9}" text-anchor="middle" class="pin-number">{pin["number"]}</text>',
            )
        )
    return "".join(output)


def _product_workflow(spec: dict[str, Any]) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-labelledby="title desc">
  <title id="title">DS-ViRe product workflow</title><desc id="desc">A synthetic datasheet page with selected pinout and table regions becomes grounded evidence and a deterministic eight-pin symbol.</desc>
  <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#070a0f"/><stop offset="1" stop-color="#0d1420"/></linearGradient><linearGradient id="paper" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#f7f9fc"/><stop offset="1" stop-color="#e7edf5"/></linearGradient><filter id="shadow"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#000" flood-opacity=".38"/></filter></defs>
  <rect width="1600" height="900" rx="32" fill="url(#bg)"/>
  <style>.eyebrow{{font:700 15px Inter,Segoe UI,sans-serif;letter-spacing:2px;fill:#18cdb2}}.title{{font:700 34px Inter,Segoe UI,sans-serif;fill:#f5f7fb}}.muted{{font:17px Inter,Segoe UI,sans-serif;fill:#8d9aad}}.paper-title{{font:700 20px Inter,Segoe UI,sans-serif;fill:#172235}}.paper-text{{font:13px Inter,Segoe UI,sans-serif;fill:#43516a}}.tiny{{font:11px Inter,Segoe UI,sans-serif;fill:#67758b}}.chip{{font:700 12px Inter,Segoe UI,sans-serif;letter-spacing:1px}}.pin{{stroke:#dfe7f2;stroke-width:3}}.pin-name{{font:700 17px Inter,Segoe UI,sans-serif;fill:#f5f7fb}}.pin-number{{font:12px ui-monospace,Consolas,monospace;fill:#7f8ca1}}.symbol-title{{font:700 22px Inter,Segoe UI,sans-serif;fill:#f5f7fb}}.mono{{font:13px ui-monospace,Consolas,monospace;fill:#8d9aad}}</style>
  <text x="64" y="70" class="eyebrow">FIGURE-LEVEL RETRIEVAL</text><text x="64" y="112" class="title">Evidence you can trace. Symbols you can reproduce.</text><text x="64" y="146" class="muted">Synthetic crop · fixture-backed output · no vendor pixels</text>
  <g filter="url(#shadow)"><rect x="64" y="190" width="570" height="625" rx="22" fill="url(#paper)"/><rect x="96" y="222" width="506" height="46" rx="8" fill="#dbe4ef"/><text x="116" y="251" class="paper-title">TKX340 · 3 A Step-Down Converter</text><text x="96" y="302" class="paper-text">4  Pin configuration and functions</text>
  <rect x="96" y="326" width="506" height="210" rx="12" fill="#fff" stroke="#18cdb2" stroke-width="4"/><rect x="250" y="365" width="198" height="130" rx="12" fill="#edf2f8" stroke="#26364d" stroke-width="3"/><circle cx="274" cy="386" r="8" fill="none" stroke="#26364d" stroke-width="3"/><g stroke="#26364d" stroke-width="2"><line x1="218" y1="388" x2="250" y2="388"/><line x1="218" y1="416" x2="250" y2="416"/><line x1="218" y1="444" x2="250" y2="444"/><line x1="218" y1="472" x2="250" y2="472"/><line x1="448" y1="388" x2="480" y2="388"/><line x1="448" y1="416" x2="480" y2="416"/><line x1="448" y1="444" x2="480" y2="444"/><line x1="448" y1="472" x2="480" y2="472"/></g><text x="349" y="432" text-anchor="middle" class="paper-title">TKX340</text><text x="349" y="458" text-anchor="middle" class="tiny">TOP VIEW</text><g class="tiny"><text x="178" y="392">BOOT 1</text><text x="193" y="420">NC 2</text><text x="193" y="448">NC 3</text><text x="160" y="476">VSENSE 4</text><text x="486" y="392">8 PH</text><text x="486" y="420">7 VIN</text><text x="486" y="448">6 GND</text><text x="486" y="476">5 ENA</text></g>
  <rect x="96" y="562" width="506" height="203" rx="12" fill="#fff" stroke="#7067f0" stroke-width="4"/><rect x="96" y="562" width="506" height="38" rx="10" fill="#e9e8fb"/><text x="116" y="587" class="paper-text">PIN</text><text x="176" y="587" class="paper-text">NAME</text><text x="300" y="587" class="paper-text">FUNCTION</text><g class="paper-text"><text x="116" y="626">1</text><text x="176" y="626">BOOT</text><text x="300" y="626">Bootstrap supply</text><text x="116" y="656">4</text><text x="176" y="656">VSENSE</text><text x="300" y="656">Feedback input</text><text x="116" y="686">6</text><text x="176" y="686">GND</text><text x="300" y="686">Power ground</text><text x="116" y="716">7</text><text x="176" y="716">VIN</text><text x="300" y="716">Input supply</text><text x="116" y="746">8</text><text x="176" y="746">PH</text><text x="300" y="746">Switching node</text></g></g>
  <rect x="108" y="340" width="112" height="30" rx="15" fill="#092b29"/><text x="164" y="360" text-anchor="middle" class="chip" fill="#18cdb2">PINOUT CROP</text><rect x="474" y="576" width="112" height="30" rx="15" fill="#211e42"/><text x="530" y="596" text-anchor="middle" class="chip" fill="#9b94ff">PIN TABLE</text>
  <path d="M675 450 C735 450 748 450 804 450" fill="none" stroke="#18cdb2" stroke-width="4" stroke-linecap="round"/><path d="M789 437 L806 450 L789 463" fill="none" stroke="#18cdb2" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><rect x="668" y="358" width="144" height="58" rx="14" fill="#101c28" stroke="#24364b"/><text x="740" y="383" text-anchor="middle" class="eyebrow" font-size="12">GROUNDED</text><text x="740" y="403" text-anchor="middle" class="mono">page · bbox · hash</text>
  <g filter="url(#shadow)"><rect x="855" y="190" width="681" height="625" rx="22" fill="#10151e" stroke="#253144"/><text x="895" y="236" class="eyebrow">DETERMINISTIC OUTPUT</text><text x="895" y="275" class="symbol-title">{spec["mpn"]} · {spec["package"]}</text><rect x="975" y="330" width="260" height="290" rx="18" fill="#161f2c" stroke="#687892" stroke-width="3"/><text x="1105" y="458" text-anchor="middle" class="symbol-title">{spec["mpn"]}</text><text x="1105" y="488" text-anchor="middle" class="mono">3 A step-down converter</text>{_symbol_pins(spec)}<text x="1105" y="692" text-anchor="middle" class="muted">8 pins · cited evidence · canonical geometry</text><text x="1105" y="724" text-anchor="middle" class="mono">validated by deterministic round-trip parsing</text></g>
</svg>
"""


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
    _write(output_root / "docs/assets/product-workflow.svg", _product_workflow(_read(SPEC)))
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

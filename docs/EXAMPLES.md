# Reproducible examples

These examples are for engineers evaluating DS-ViRe and for maintainers writing
technical posts about it. Every number and visual below is generated from a
committed JSON artifact. Vendor PDFs and rendered datasheet crops are not
redistributed.

Regenerate all public examples:

```bash
python scripts/generate_docs_assets.py
git diff --exit-code -- examples docs/assets
```

CI performs the same byte comparison in a temporary directory. Do not edit the
generated JSON or SVG files by hand.

## Evidence bundle walkthrough

![Source-free DS-ViRe evidence bundle](assets/evidence-bundle-example.svg)

The generated [evidence summary](../examples/tps5430ddar-evidence-summary.json)
is derived from the schema-validated
[`dsvire.symbol-evidence.v2`](../fixtures/evidence/tps5430ddar.json) fixture. It
demonstrates the boundary DS-ViRe gives a downstream client:

- exact manufacturer, orderable MPN, and package identity;
- typed `pinout`, `table`, and `package` regions instead of a whole PDF page;
- one-based page number and normalized `[x0, y0, x1, y1]` geometry;
- a content hash for each rendered crop;
- the method, policy version, outcome, numerical score, and score semantics.

The values `0.97`, `0.94`, and `1.00` are
`heuristic_evidence_strength`. They are not probabilities. The example sets
`publication_eligible` to `false` because the Technical Bible permits automated
publication only after an independently reviewed, held-out-calibrated
`evidence_gated_visual` policy passes its SLO. An `accepted` heuristic region
means the deterministic baseline found evidence; it does not mean EGVV has
verified the crop.

This fixture is a stable contract sample, not a current production extraction
or benchmark result. Its source identity and hashes are frozen so schema and
downstream compatibility can be tested without committing copyrighted bytes.

## Development comparator benchmark

![Text-layout and RapidOCR development benchmark](assets/multivendor-development-benchmark.svg)

The graph is generated from
[`multivendor-development-2026-08-12.json`](../evaluation/results/multivendor-development-2026-08-12.json),
a frozen five-document, 34-case development snapshot. It is intentionally
smaller than the living registry. The snapshot preserves a reproducible
comparison while the registry grows.

| Measurement | Text layout | RapidOCR |
|---|---:|---:|
| Elapsed time | 0.527 s | 116.12 s |
| Throughput | 9.49 docs/s | 0.043 docs/s |
| Peak RSS | 69.4 MiB | 632.8 MiB |
| Positive mean similarity | 0.763 | 0.796 |
| Wrong-package mean similarity | 0.700 | 0.587 |
| Wrong-variant mean similarity | 0.600 | 0.484 |
| Wrong-figure mean similarity | 0.581 | 0.569 |

RapidOCR improved package and variant separation in this slice, but the
wrong-package and wrong-figure scores remain too close to positives for a safe
standalone verifier. No threshold was fitted. Both adapters report similarity,
not calibrated probability, and this owner-authorized agent-audited development result is
ineligible for calibration or publication policy.

To produce a fresh local comparator result from official, hash-pinned sources:

```bash
python scripts/evaluate_visual.py \
  --cache-dir .cache/dsvire-eval \
  --adapter text-layout \
  --json-out visual-text-layout.json
```

Use `--offline` after the exact PDFs are cached. A vendor URL that returns
different bytes is an error requiring source revision review; the runner never
silently accepts the new document.

## Authenticated service load evidence

![DS-ViRe authenticated service load evidence](assets/service-load-evidence.svg)

The source-free summary
[`service-load-linux-2026-08-12.json`](../evaluation/results/service-load-linux-2026-08-12.json)
is derived from the schema-validated artifact published by GitHub Actions run
[`31632587220`](https://github.com/TokitoAI/tokito-dsvire/actions/runs/31632587220).
It binds exact commit `ab36220afb0b1f5bbcea82a62633c5fc52f1dd47`, workload
digest `a438fcd...b24ff`, full artifact digest `4e7a7cf...f799`, the runner
environment, service limits, and these measurements:

| Phase | Result |
|---|---:|
| Cold PDF-to-evidence p95 | 623.588 ms (2/2 success) |
| Warm/cache phase p95 | 612.045 ms (4/4 success) |
| Warm steady cached samples | 202.818–219.750 ms |
| Overload | 1 progress, 5 HTTP 503 rejections in 102.610–104.796 ms |
| Peak Uvicorn + worker process-tree RSS | 174,796,800 bytes (166.7 MiB) |
| Durable output | 4 packs, 261,650 bytes, zero scratch/partial residue |

This deliberately starts a real Uvicorn process and crosses bearer
authentication, TCP request parsing, bounded admission, the spawned PDF worker,
pack creation/cache validation, and shutdown cleanup. The input is a
deterministic generated two-page PDF, so it redistributes no vendor content.

The Technical Bible's 800 ms p95 target applies to the future hot-pack MaxSim
query path. This run measures synchronous PDF-to-evidence indexing, so its SLO
verdict is `not_applicable`; the latency is evidence, not a claim that the
future query SLO passes. It also excludes Cloud upload/blob I/O, extraction,
catalog publication, Companion projection, client network latency, and soak.

Run the same harness locally with:

```bash
uv run --frozen --no-sync python scripts/evaluate_service_load.py \
  --cold-requests 2 --warm-requests 4 --overload-requests 6 \
  --source-commit "$(git rev-parse HEAD)" \
  --json-out service-load-evidence.json
```

## Inspecting a result safely

When consuming an evidence region, interpret these fields together:

```json
{
  "type": "pinout",
  "page": 3,
  "bbox_norm": [0.229, 0.126, 0.776, 0.328],
  "verification": {
    "method": "text_layout_heuristic",
    "outcome": "accepted",
    "score": 0.97,
    "score_semantics": "heuristic_evidence_strength"
  }
}
```

Never branch on `score` without also checking `method`, `policy_version`,
`outcome`, and `score_semantics`. A future calibrated probability belongs to a
different method and frozen policy artifact; raw similarity and heuristic
strength must not be relabelled as confidence.

## What the examples do not prove

They do not prove production accuracy, the 2% verified-path wrong-figure SLO,
or zero wrong-variant acceptance. Those require independently reviewed,
family-isolated calibration/evaluation splits and a policy frozen before the
held-out run. Current evidence and missing gates are tracked in
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

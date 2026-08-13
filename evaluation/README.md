# Evaluation

DS-ViRe evaluates figure-level retrieval on frozen document, crop, query, and
relevance-judgment manifests. Results are reproducible artifacts, not values
copied into documentation by hand.

## Current benchmark

The current development cycle uses one candidate universe for every system:

| Property | Value |
|---|---:|
| Documents | 30 |
| Crop candidates | 209 |
| Queries | 90 |
| Ranked query-candidate pairs | 18,810 |
| Query intents | pinout, package, table |

![Model comparison](../docs/assets/benchmark-overview.svg)

| System | nDCG@5 | Recall@5 | MAP |
|---|---:|---:|---:|
| Lexical + layout | 0.963 | 1.000 | 0.950 |
| OpenCLIP | 0.100 | 0.122 | 0.120 |
| ColSmol-256M | 0.417 | 0.544 | 0.395 |

The lexical baseline benefits from exact part-number, pin-label, and table-text
overlap. OpenCLIP and ColSmol measure visual-semantic retrieval on the same
crops and judgments. These are development results, not held-out production
claims.

## Artifact layout

```text
evaluation/
├── corpus/       # registered source metadata and immutable digests
├── crops/        # crop manifests and provenance
├── queries/      # query definitions and relevance judgments
├── rankings/     # complete ranked outputs per system
├── results/      # schema-validated metric summaries
└── splits/       # frozen development and holdout membership
```

Generated PDFs and rendered page images remain untracked. Public evaluation
fixtures are synthetic or redistributable; vendor datasheet pixels are not
committed to the repository.

## Reproduce the development results

Set up the repository as described in [Usage](../docs/USAGE.md), then run:

```bash
uv run pytest -q
uv run python scripts/generate_docs_assets.py
```

The result files used by the comparison graphic are:

- `results/full-corpus-text-pdfium-development-2026-08-13.json`
- `results/full-corpus-openclip-pdfium-development-2026-08-13.json`
- `results/full-corpus-colsmol-development-2026-08-13.json`

Each result records its source ranking digest, runtime metadata, limitations,
aggregate metrics, and metrics by query intent. The JSON schemas live under
`scripts/schema/`; tests reject incompatible or internally inconsistent files.

## Evaluation protocol

1. Freeze document identity and SHA-256 digests.
2. Generate crops and freeze their page coordinates and source digest.
3. Define queries and relevance judgments without reading model rankings.
4. Run every comparator against the identical candidate universe.
5. Persist the complete ranking, not only aggregate metrics.
6. Validate schemas and recompute result digests.
7. Generate documentation visuals from the committed result files.

Changes to documents, crops, queries, judgments, model identity, or scoring
logic require a new cycle. Historical artifacts remain immutable so published
numbers can be traced to an exact protocol.

## Leakage controls

- A document identity cannot cross development and holdout splits.
- Near-duplicate document families stay in one split.
- Query authors do not inspect model rankings before judgments are frozen.
- Acceptance fixtures are not reported as retrieval benchmark results.
- Threshold selection uses development data only.
- Holdout evaluation is a release-gated operation and is not represented by the
  development table above.

## Visual-verifier calibration

The optional visual verifier is calibrated separately from retrieval. Its
inputs are retrieved crops plus structured extraction candidates; its output is
an accept, reject, or abstain decision. Calibration artifacts must record model
identity, prompt digest, decision threshold, and the exact labeled sample set.
They must not be mixed with retrieval relevance judgments.

## Adding a comparator

A new model comparison must:

- consume the frozen query and candidate manifests;
- emit one deterministic ranking entry for every query-candidate pair;
- identify model weights, preprocessing, device, and precision;
- use the shared metric implementation and result schema;
- include limitations and runtime metadata; and
- regenerate `docs/assets/benchmark-overview.svg` from committed evidence.

Do not add screenshots of dashboards or manually drawn score charts. The public
graphic is generated so its values cannot drift from the evaluation artifacts.

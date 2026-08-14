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

## Cycle v4 human authoring handoff

Cycle v4 stops at a score-free packet until two different GitHub humans finish
the authoring and review boundary below. Agents may validate files and operate
the tooling, but must not write or rewrite query text, choose regions, create
either attestation, approve the submission, or inspect model rankings. The
current packet identity is:

```text
DSVIRE_SOURCE_MANIFEST_SHA256=d6398ed9ea4ea5da7f8b726e030d2f77c94979705856c235d3aca8f8973fb9c6
DSVIRE_AUTHORING_PACKET_SHA256=021118687daf969490ee0f5b6289de4549e42bb76fe63d0038fe96c28ba5cb68
```

### 1. Reproduce the score-free review material

Use a private scratch directory outside Git. Acquire only the official sources
named by the frozen plan, then reproduce the page renders and packet. The
source cache and rendered pages are `download_only` review material and must
not be committed.

```sh
python scripts/acquire_retrieval_cycle_sources.py \
  --plan evaluation/retrieval_cycle_v4_preregistration.json \
  --cache "$DSVIRE_V4_WORK/sources" \
  --out "$DSVIRE_V4_WORK/source-manifest.json"

python scripts/prepare_retrieval_authoring.py prepare \
  --plan evaluation/retrieval_cycle_v4_preregistration.json \
  --manifest evaluation/retrieval_cycle_v4_source_manifest.json \
  --source-dir "$DSVIRE_V4_WORK/sources" \
  --packet-out "$DSVIRE_V4_WORK/packet.json" \
  --template-out "$DSVIRE_V4_WORK/submission.json" \
  --pages-out "$DSVIRE_V4_WORK/pages"

python scripts/prepare_retrieval_authoring.py validate-packet \
  --packet "$DSVIRE_V4_WORK/packet.json"
```

The acquisition command must report `complete: true`, 12 sources, zero
invalidations, and the source-manifest identity above. The last command must
print the packet identity above. Stop on any changed source, redirect, render,
digest, invalidation, or document count; do not substitute a mirror, family, or
PDF revision.

### 2. Human A authors the submission

Starting from `evaluation/retrieval_cycle_v4_authoring_submission.template.json`,
Human A reviews only the reproduced pages and score-free packet. They complete
all 12 documents with exactly:

- three positive regions: one each for `pinout`, `table`, and `package`;
- all four hard-negative kinds: `wrong_intent`, `wrong_package`,
  `wrong_variant`, and `wrong_view`;
- six natural queries: two per intent, with explicit relevant and hard-negative
  region links; and
- `author: github:<their-login>` plus an honest attestation containing both
  `human-authored` and `no model`.

The schema and semantic validator reject missing strata, invalid boxes/pages,
duplicate or label-bearing query text, incorrect relevance links, and any
packet mismatch. Finalize to a new file; never edit the digest by hand:

```sh
python scripts/prepare_retrieval_authoring.py finalize-submission \
  --packet evaluation/retrieval_cycle_v4_authoring_packet.json \
  --submission "$DSVIRE_V4_WORK/submission.json" \
  --out "$DSVIRE_V4_WORK/submission.final.json"
```

Human A opens a PR containing the finalized source-free submission and adds a
GitHub PR review whose body contains these exact lines:

```text
DSVIRE_AUTHORING_SUBMISSION_SHA256=<digest printed by finalize-submission>
HUMAN_AUTHORED_NO_MODEL=TRUE
```

The review must be authored by the same login declared in the submission. A
plain issue/PR comment is not sufficient: the seal binds the immutable GitHub
review URL and its exact `submitted_at` timestamp.

### 3. Human B independently reviews

Human B must be a different GitHub login. Without inspecting rankings or model
scores, they check every region, box, intent, view, query, and relevance link
against the reproduced pages. If anything changes, Human A must re-finalize and
re-attest the new submission digest before review resumes.

Human B submits an **APPROVED GitHub PR review** containing these exact lines:

```text
DSVIRE_AUTHORING_PACKET_SHA256=021118687daf969490ee0f5b6289de4549e42bb76fe63d0038fe96c28ba5cb68
DSVIRE_AUTHORING_SUBMISSION_SHA256=<finalized submission digest>
DSVIRE_INDEPENDENT_HUMAN_REVIEW=TRUE
```

### 4. Bind GitHub provenance and seal

Create a review record matching
`scripts/schema/retrieval_authoring_review_v1.schema.json`. Populate the author
and reviewer URLs with their `#pullrequestreview-<id>` URLs, and copy each
review object's exact `submitted_at` value into `author_attested_at` or
`reviewed_at`. Set `reviewer` to `github:<Human-B-login>`. Do not hand-type an
approximate timestamp.

Export `GITHUB_TOKEN` from the operator's secret store with permission to read
the PR reviews; never paste it into a review, commit, or command-line argument.
Then create and validate the seal:

```sh
python scripts/prepare_retrieval_authoring.py seal \
  --packet evaluation/retrieval_cycle_v4_authoring_packet.json \
  --submission "$DSVIRE_V4_WORK/submission.final.json" \
  --review "$DSVIRE_V4_WORK/review.json" \
  --out "$DSVIRE_V4_WORK/seal.json"

python scripts/prepare_retrieval_authoring.py validate-seal \
  --packet evaluation/retrieval_cycle_v4_authoring_packet.json \
  --submission "$DSVIRE_V4_WORK/submission.final.json" \
  --seal "$DSVIRE_V4_WORK/seal.json"
```

The seal command fetches both GitHub review objects and fails closed unless the
logins, states, URLs, timestamps, packet/submission digests, and marker lines
all match and the humans are distinct. Only a committed seal that passes this
validation authorizes score access. It does not imply the frozen calibration
or held-out evaluation passed, and it does not enable publication.

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

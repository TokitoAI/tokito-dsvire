# tokito-dsvire

Figure-level search over semiconductor datasheets.

Current release: **v0.3.1**. See [`CHANGELOG.md`](CHANGELOG.md).

Pinouts, package drawings, timing diagrams, and application circuits live in the pictures, not in OCR text. This project indexes those regions with a vision-first cascade, returns crops with page and bbox provenance, and stays small enough to query without stuffing a 400-page PDF into a model.

**DS-ViRe** is the retrieval system and its growing open, source-free benchmark.

![Source-free DS-ViRe evidence bundle](docs/assets/evidence-bundle-example.svg)

## Why

Text RAG on datasheets misses drawings. Full-page ColPali-style indexes work, but they are heavy and still return whole pages when you need a pin map. DS-ViRe treats **figures and tables as the retrieval unit**, uses layout detection as a compute gate, and keeps text (TOC, captions, pin names) as a cheap filter and pin lexicon.

## Status

| Piece | State |
|---|---|
| Architecture spec | In [`docs/TECHNICAL_BIBLE.md`](docs/TECHNICAL_BIBLE.md) |
| Benchmark | Public source-free registry: 40 official families and 279 positive/adversarial cases across 14 manufacturer labels and 32 component categories; 30 are development, five calibration, and five reviewed evaluation families. The generated [coverage ledger](examples/corpus-coverage.json) records the honest Technical Bible gap: 40/500 documents and 90/2,000 explicit natural-language queries. |
| Deterministic retrieval baseline | Implemented in `src/dsvire`; bounded PDF parsing, exact text-grounded identity/package abstention, figure/table scoring, and frozen evidence output |
| Evidence contract fixture | Current v2 TPS5430 evidence metadata is schema-tested in `fixtures/evidence`; generated output is not checked into the repository |
| Hosted service image | Implemented baseline; private `/v1/evidence/symbol` API with mandatory production bearer, bounded admission, killable PDF workers, and container readiness check |
| Service load evidence | Real authenticated Linux HTTP/worker boundary: cold p95 623.6 ms, warm p95 612.0 ms, five bounded overload rejections, 166.7 MiB peak process-tree RSS, and zero scratch/partial residue; generated 12-request evidence, not capacity or MaxSim SLO proof |
| Visual comparators / benchmark corpus | Text-layout was frozen after comparison with RapidOCR and pinned OpenCLIP; held-out evaluation accepted zero wrong figures/identities but reached 46.7% positive coverage versus the frozen 50% minimum, so the gate failed and publication remains disabled |
| Tokito Wave D integration | Seeded acceptance crosses authenticated Cloud ingestion, immutable generated SQLite, catalog sync, MCP streamable HTTP resolve/provenance, and Desktop place/save/reopen with exact compiler bytes. See [`examples/wave-d-acceptance.json`](examples/wave-d-acceptance.json). |

## Start here

- [Technical Bible](docs/TECHNICAL_BIBLE.md) — canonical architecture, evidence contract, benchmark, and SLOs.
- [Reproducible examples](docs/EXAMPLES.md) — commands, source-free evidence screenshot, values, benchmark graph, and interpretation.
- [Production readiness](docs/PRODUCTION_READINESS.md) — evidence ledger and honest remaining gates.
- [Contracts](docs/CONTRACTS.md) — versioned machine-facing schemas.

Regenerate the public JSON and SVG examples from committed evidence:

```bash
python scripts/generate_docs_assets.py
git diff --exit-code -- examples docs/assets
```

Generated assets are byte-checked in CI. The script derives values from the
committed fixture and benchmark JSON; it does not contain a second set of
hand-maintained benchmark numbers.

![Corpus coverage against Technical Bible targets](docs/assets/corpus-coverage.svg)

The 279 visual annotations are not relabelled as 279 benchmark queries. A
separate, strictly grounded query registry counts 90 deterministic-template
development queries—three intents for each development family—and the ledger
reports them separately from manual or independently reviewed queries. This
keeps corpus growth measurable without overstating accuracy,
representativeness, held-out performance, or legal approval.

Query registry v2 also binds graded relevant regions and explicit adversarial
regions. The source-free evaluator computes nDCG@5, R@5, mAP, MRR, abstention,
and hard-negative exposure from digest-bound system rankings. The checked
perfect-score canary validates metric plumbing over a closed judged pool; it is
not a retriever benchmark or production accuracy claim. See
[`docs/EXAMPLES.md`](docs/EXAMPLES.md#query-ranking-measurement-contract).

The fixture runner is intentionally not presented as an upload product. The
public upload boundary belongs to Tokito Cloud at `https://api.tokito.dev`;
DS-ViRe runs behind it on the private service network. The baseline never
guesses manufacturer, MPN, or package and will fail closed unless the PDF text
contains the manufacturer plus a token-bounded exact MPN associated with the
requested package. It also requires a pinout and pin-function table. This is a
deterministic safety gate, not calibrated visual verification.

## Run and verify

```bash
uv sync --locked --extra test
uv run --frozen --no-sync pytest
uv run --frozen --no-sync dsvire extract-evidence datasheet.pdf \
  --manufacturer 'Texas Instruments' \
  --mpn TPS5430DDAR \
  --package SO-PowerPAD-8 \
  --out ./artifacts
```

Development and release environments are resolved from the committed universal
`uv.lock`. Use uv 0.12.3 and follow
[`docs/DEPENDENCY_LOCKS.md`](docs/DEPENDENCY_LOCKS.md) when changing a dependency;
CI rejects stale locks and stale container exports.

Run the same aggregate gate used by CI and tagged releases with:

```bash
uv run --frozen --no-sync python scripts/verify_release.py \
  --json-out release-verification.json
```

With sibling `tokito`, `tokito-ai`, `tokito-catalog`, and `tokito-mcp`
checkouts, reproduce the seeded product-level acceptance with:

```bash
python scripts/wave_d_acceptance.py
```

This command makes no model call. Its checked EGVV evidence/spec pair is the
explicit seed; every downstream boundary is the real production path. Live
extractor qualification remains a separate production-readiness gate.

For the hosted service, build the image and send raw `application/pdf` bytes to
`POST /v1/evidence/symbol` with the exact identity as query parameters. The
service accepts at most 64 MiB and 2,000 pages per document. Production and
staging refuse to start without a `DSVIRE_SERVICE_TOKEN` of at least 32 bytes;
do not expose this private endpoint to desktop clients. CPU-heavy parsing runs
in a disposable subprocess and admission is bounded before request bodies are
buffered. The container entrypoint performs configuration and persistent-volume
preflight in PID 1 before starting Uvicorn workers, so unsafe startup exits
nonzero for orchestrators and CI.

Run the hash-pinned, download-only real-PDF identity regression slice with:

```bash
python scripts/evaluate_identity.py \
  --cache-dir .cache/dsvire-eval \
  --json-out identity-eval.json
```

See [`evaluation/README.md`](evaluation/README.md) for provenance, split, and
leakage rules. The seed registry is development evidence, not calibration.

Local unauthenticated development must be explicit and loopback-only:

```bash
DSVIRE_ENVIRONMENT=development DSVIRE_ALLOW_INSECURE_DEV=true \
  uvicorn dsvire.api:app --host 127.0.0.1 --port 8081
```

Production controls can be tuned per API process with
`DSVIRE_MAX_CONCURRENT_JOBS`, `DSVIRE_ADMISSION_TIMEOUT_SECONDS`,
`DSVIRE_JOB_TIMEOUT_SECONDS`, `DSVIRE_WORKER_CPU_SECONDS`,
`DSVIRE_WORKER_MEMORY_BYTES`, `DSVIRE_WORKER_FILE_BYTES`, and
`DSVIRE_MAX_PDF_BYTES` (lower than the 64 MiB hard ceiling). Invalid or unsafe
values fail startup.

## Docs

- [Technical bible](docs/TECHNICAL_BIBLE.md): problem, related work, architecture, stack, SLOs, benchmark design
- [Production-readiness audit](docs/PRODUCTION_READINESS.md): evidence, findings, priorities, and remaining gates
- [Dependency locks](docs/DEPENDENCY_LOCKS.md): frozen install and intentional update procedure

## Layout

```text
src/dsvire/ # deterministic baseline, CLI, and hosted service
fixtures/    # contract/evidence fixture metadata (no redistributed PDFs)
scripts/     # fixture builder, vertical-slice runner, and verifier
docs/        # specification
```

## Related work

Starts from ColPali / ColQwen, ViDoRe, DocLayout-YOLO, and datasheet layout taxonomies (DocEDA / EDocNet). Closest gap: open **figure-grounded** retrieval for electronics datasheets, not another text extractor or schematic-to-netlist tool.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Manufacturer PDFs are not redistributed. Benchmark releases will ship hashes, URLs, and annotation files.

## Citation

See [CITATION.cff](CITATION.cff).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue before large design changes; the bible is the contract until code lands.

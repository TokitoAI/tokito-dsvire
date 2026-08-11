# tokito-dsvire

Figure-level search over semiconductor datasheets.

Current release: **v0.1.1**. See [`CHANGELOG.md`](CHANGELOG.md).

Pinouts, package drawings, timing diagrams, and application circuits live in the pictures, not in OCR text. This project indexes those regions with a vision-first cascade, returns crops with page and bbox provenance, and stays small enough to query without stuffing a 400-page PDF into a model.

**DS-ViRe** is the name of the retrieval problem and the planned open benchmark.

## Why

Text RAG on datasheets misses drawings. Full-page ColPali-style indexes work, but they are heavy and still return whole pages when you need a pin map. DS-ViRe treats **figures and tables as the retrieval unit**, uses layout detection as a compute gate, and keeps text (TOC, captions, pin names) as a cheap filter and pin lexicon.

## Status

| Piece | State |
|---|---|
| Architecture spec | In [`docs/TECHNICAL_BIBLE.md`](docs/TECHNICAL_BIBLE.md) |
| Benchmark design | Specced; corpus and labels not released yet |
| Deterministic retrieval baseline | Implemented in `src/dsvire`; bounded PDF parsing, exact text-grounded identity/package abstention, figure/table scoring, and frozen evidence output |
| Native symbol proof | Real TPS5430 crops compiled to a validated `.tokito_sym`; see the evidence, render, and reproducible checks in the example |
| Hosted service image | Implemented baseline; private `/v1/evidence/symbol` API with mandatory production bearer, bounded admission, killable PDF workers, and container readiness check |
| Vision-model reranker / benchmark corpus | Not yet implemented; the baseline abstains when structural evidence is insufficient |

The fixture runner is intentionally not presented as an upload product. The
public upload boundary belongs to Tokito Cloud at `https://api.tokito.dev`;
DS-ViRe runs behind it on the private service network. The baseline never
guesses manufacturer, MPN, or package and will fail closed unless the PDF text
contains the manufacturer plus a token-bounded exact MPN associated with the
requested package. It also requires a pinout and pin-function table. This is a
deterministic safety gate, not calibrated visual verification.

## Run and verify

```bash
python -m pip install -e '.[test]'
pytest
dsvire extract-evidence datasheet.pdf \
  --manufacturer 'Texas Instruments' \
  --mpn TPS5430DDAR \
  --package SO-PowerPAD-8 \
  --out ./artifacts
```

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
- [Real TPS5430 symbol proof](docs/examples/tps5430ddar.md): verified crops, audited pin spec, native `.tokito_sym`, and rendered output

## Layout

```text
src/dsvire/ # deterministic baseline, CLI, and hosted service
fixtures/    # contract/evidence fixture metadata (no redistributed PDFs)
artifacts/   # reproducible public sample outputs
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

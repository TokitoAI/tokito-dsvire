# tokito-dsvire

Figure-level search over semiconductor datasheets.

Pinouts, package drawings, timing diagrams, and application circuits live in the pictures, not in OCR text. This project indexes those regions with a vision-first cascade, returns crops with page and bbox provenance, and stays small enough to query without stuffing a 400-page PDF into a model.

**DS-ViRe** is the name of the retrieval problem and the planned open benchmark.

## Why

Text RAG on datasheets misses drawings. Full-page ColPali-style indexes work, but they are heavy and still return whole pages when you need a pin map. DS-ViRe treats **figures and tables as the retrieval unit**, uses layout detection as a compute gate, and keeps text (TOC, captions, pin names) as a cheap filter and pin lexicon.

## Status

| Piece | State |
|---|---|
| Architecture spec | In [`docs/TECHNICAL_BIBLE.md`](docs/TECHNICAL_BIBLE.md) |
| Benchmark design | Specced; corpus and labels not released yet |
| Deterministic retrieval baseline | Implemented in `src/dsvire`; bounded PDF parsing, figure/table scoring, verified crops, and frozen evidence output |
| Hosted service image | Implemented; private `/v1/evidence/symbol` API with optional service bearer and container healthcheck |
| Vision-model reranker / benchmark corpus | Not yet implemented; the baseline abstains when structural evidence is insufficient |

The fixture runner is intentionally not presented as an upload product. The
public upload boundary belongs to Tokito Cloud at `https://api.tokito.dev`;
DS-ViRe runs behind it on the private service network. The baseline never
guesses manufacturer, MPN, or package and will fail closed when it cannot
verify both a pinout and a pin-function table.

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
service accepts at most 64 MiB and 2,000 pages per document. Set
`DSVIRE_SERVICE_TOKEN` in production; do not expose this private endpoint to
desktop clients.

## Docs

- [Technical bible](docs/TECHNICAL_BIBLE.md): problem, related work, architecture, stack, SLOs, benchmark design

## Layout

```text
src/dsvire/ # deterministic baseline, CLI, and hosted service
configs/     # pinned model SHAs, DPI, SLO targets
scripts/     # corpus download, reproduce eval tables
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

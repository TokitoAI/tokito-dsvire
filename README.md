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
| Index / query implementation | Not started |

## Docs

- [Technical bible](docs/TECHNICAL_BIBLE.md): problem, related work, architecture, stack, SLOs, benchmark design

## Planned layout

```text
packages/    # core, index, query, bench (upcoming)
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

# tokito-dsvire

**DS-ViRe** — *Datasheet Visual Retrieval* for electronics.

Figure-level, vision-first retrieval over semiconductor datasheets: pinouts, package drawings, timing graphs, reference circuits — not whole-PDF dumps into a model, and not text-only RAG.

> Existing electronics RAG systems retrieve text or whole PDFs; schematic vision systems recover netlists. DS-ViRe retrieves **grounded figures/regions** with EDA-aware indexing and electrical consistency checks.

This repository is the **open-source home** for the DS-ViRe specification, benchmark, and (upcoming) index/query implementation. It is developed alongside [Tokito](https://github.com/VtronTokito/tokito) but is a **separate public project** — Tokito itself remains private.

## Status

| Area | State |
|---|---|
| Technical bible / architecture | **Published** in this repo |
| Benchmark (DS-ViRe) | Specced — corpus & labels next |
| Index / query code | **Not started** (intentional) |
| Papers | Portfolio defined in the bible |

## Docs

- **[Technical bible](docs/TECHNICAL_BIBLE.md)** — problem, related work, architecture, stack, SLOs, benchmark design, paper portfolio, roadmap

## What this is / is not

| Is | Is not |
|---|---|
| Open research + production-oriented retrieval system | A wrapper that only “runs ColPali on PDFs” |
| Figure/region IR for datasheets | Schematic → netlist (see OmniSch / SINA) |
| Upstream for Tokito agents via API/MCP (planned) | The Tokito desktop app source |

## Planned layout

```text
tokito-dsvire/
  docs/TECHNICAL_BIBLE.md   # canonical spec
  packages/                 # upcoming: core, index, query, bench
  configs/                  # pinned model SHAs, DPI, SLOs
  scripts/                  # corpus download, reproduce tables
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Model weights used later will carry their own upstream licenses (documented in `NOTICE` as they are added).

## Citation

See [CITATION.cff](CITATION.cff). Until a paper DOI exists, cite this repository and the technical bible.

## Related

- Org: [VtronTokito](https://github.com/VtronTokito)
- Product context: Tokito desktop schematic studio (private)
- Inspiration / baselines: [ColPali](https://arxiv.org/abs/2407.01449), [ViDoRe](https://arxiv.org/abs/2601.08620), DocLayout-YOLO, DocEDA / EDocNet

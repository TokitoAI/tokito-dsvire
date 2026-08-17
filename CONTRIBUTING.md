# Contributing

Thanks for interest in tokito-dsvire.

## Before you write code

1. Read [`docs/TECHNICAL_BIBLE.md`](docs/TECHNICAL_BIBLE.md). That doc is the contract.
2. Open an issue for design changes (new index units, model swaps, pack format breaks).
3. Check the project board and open an issue before substantial design changes.

## PRs

- Keep PRs focused.
- Do not commit datasheet PDFs, packs, or API keys.
- If you change architecture or SLOs, update the technical bible in the same PR.
- Prefer reproduce scripts for any number you claim in a table or README.

## Dataset contributions

Dataset work belongs under [`datasets/`](datasets/), while frozen benchmark
registries remain under [`evaluation/`](evaluation/). Start from
[`datasets/corpus-v1/CONTRIBUTION.template.json`](datasets/corpus-v1/CONTRIBUTION.template.json)
and open an issue before a bulk acquisition.

- Submit source URLs, immutable hashes, source-term evidence, validation
  outcomes, and original annotations. Do not submit third-party PDF bytes
  without an explicit redistribution license covering the repository's use.
- Check source URL, final redirect URL, content hash, and normalized part-family
  markers against every sealed calibration/evaluation registry.
- Treat catalog names as weak labels. Exact identity, package, pin-row, region,
  and relevance labels require evidence specific to each assertion.
- Cluster document revisions and related orderable parts before assigning a
  development split. Random hash splitting is not acceptable.
- Quarantine malformed, encrypted, repaired, duplicate, off-domain, or
  identity-ambiguous inputs instead of silently admitting them.

Corpus work is tracked on the Tokito product board through
[Tokito issue #479](https://github.com/TokitoAI/tokito/issues/479).

## License

Contributions are under Apache License 2.0 (see [LICENSE](LICENSE)).

# DS-ViRe datasets

This directory publishes the source registries, integrity ledgers, weak labels,
and annotations used to construct DS-ViRe corpora. It deliberately separates
three things that are often conflated:

1. **Source registry** — where a document came from and which immutable digest
   identifies the bytes.
2. **Training eligibility** — what the available evidence permits the document
   to supervise.
3. **Evaluation eligibility** — whether the document is outside every sealed
   calibration and evaluation family.

[`corpus-v1`](corpus-v1/) is the first large acquisition tranche. The manifest
is public and reproducible; manufacturer PDF bytes remain in private,
content-addressed caches. A URL being public does not itself grant permission to
mirror the corresponding document.

Dataset changes are tracked by
[Tokito project issue #479](https://github.com/TokitoAI/tokito/issues/479) and
the [Tokito product board](https://github.com/orgs/TokitoAI/projects/1).

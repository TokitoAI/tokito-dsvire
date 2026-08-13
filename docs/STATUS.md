# Project status

DS-ViRe is an actively developed research and production-engineering project.
The current release is **v0.4.1**.

## Implemented

- strict PDF preflight and PDFium rendering;
- exact manufacturer, token-bounded MPN, and package-association grounding;
- figure/table proposals and a deterministic text-layout baseline;
- typed evidence v2 with page, bounding box, crop hash, verification policy,
  model identity, and source provenance;
- authenticated HTTP service with bounded admission and killable workers;
- content-addressed, atomically published evidence packs;
- source-free visual registries and family-isolated evaluation tooling;
- BM25, dense, RRF, and bounded late-interaction MaxSim query core;
- pinned ColSmol-256M integration and reproducibility evidence;
- immutable dependency/model/source contracts, container build evidence,
  runtime license policy, and hostile-PDF regression gates;
- Tokito Cloud upload/job integration and deterministic evidence-to-symbol
  contracts.

## Deliberately not enabled

Automated generated-symbol publication is disabled. The last frozen held-out
cycle accepted no wrong figure or wrong identity but reached 46.7% positive
coverage against a preregistered 50% minimum. The threshold was not changed
after seeing evaluation results.

Cycle v4 has exact sealed sources and a score-free authoring packet. It still
requires genuinely human-authored natural queries and a different independent
human reviewer before calibration or evaluation scores may be accessed.

## Remaining production gates

- pass a newly preregistered, independently reviewed calibrated visual cycle;
- integrate only the resulting passing evidence-gated visual policy;
- expand representative legal corpus coverage and manual queries;
- add longer representative workload/availability evidence;
- complete automated encrypted off-host backup replication and recovery;
- use a separately scoped extractor credential instead of the currently
  owner-authorized shared Anthropic credential.

The detailed work and ownership live on the
[Tokito project board](https://github.com/orgs/TokitoAI/projects/1). Raw,
source-free benchmark and operational evidence remains under `evaluation/` for
reproducibility rather than being duplicated into this reader-facing page.

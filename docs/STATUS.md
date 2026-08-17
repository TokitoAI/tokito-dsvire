# Project status

DS-ViRe is an actively developed research and production-engineering project.
The current release is **v0.5.0**.

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
- authenticated, bounded hybrid query API over digest-addressed, model-bound
  retrieval packs with killable execution and provenance-rich results;
- pinned ColSmol-256M integration and reproducibility evidence;
- immutable dependency/model/source contracts, container build evidence,
  runtime license policy, and hostile-PDF regression gates;
- Tokito Cloud upload/job integration and deterministic evidence-to-symbol
  contracts.
- production worker operation with an owner-authorized Anthropic credential,
  fail-closed provider-backed canaries, encrypted integrity-verified off-host
  recovery points, independent retention, and 24-hour RPO alerting.

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
- implement the approved standalone service boundary: Postgres catalog control
  plane, object-backed private artifacts, rebuildable Qdrant indexes,
  Redis-compatible ephemeral cache/realtime acceleration, and verified
  immutable SQLite publication packs;
- ship and verify contract-equivalent CLI/API/MCP/web/self-hosted upload,
  evidence review, deterministic bundle download, and explicit optional catalog
  contribution flows. The planned `dsvire.tokito.dev` boundary is not currently
  a shipped public standalone service;
- prove the 99.5% query-API availability target over a representative duration
  and workload. An authenticated one-minute semantic canary is live against a
  digest-addressed, source-free synthetic pack and validates the exact response
  schema, pack/content provenance, and expected top region. Its preregistered
  seven-day evidence window is still collecting; initial deployment samples do
  not establish the SLO;
- perform a decrypt/restore drill from the independent replica with the
  operator-held age identity.

The production operational canary uses three exact-hash, previously consumed
development datasheets from TI, Microchip, and Diodes. All three completed in
11.903 seconds with one attempt each, safely abstained, published nothing,
released their source bytes, and left ready workers with zero active jobs,
missing blobs, or worker errors. This proves the live provider and fail-closed
boundary, not retrieval quality, cycle-v4 evaluation, or the availability SLO.

The separate query-availability canary has no publication capability and uses
no vendor document bytes. Prometheus records bounded outcome classes and
latency, alerts on semantic failure and sample-gated SLO burn, and the evidence
exporter refuses windows below 99% scheduled-probe coverage. This measures the
authenticated query service boundary only; it cannot substitute for cycle-v4
retrieval-quality evaluation.

The detailed work and ownership live on the
[Tokito project board](https://github.com/orgs/TokitoAI/projects/1). Raw,
source-free benchmark and operational evidence remains under `evaluation/` for
reproducibility rather than being duplicated into this reader-facing page.

# Project status

DS-ViRe is an actively developed research and production-engineering project.
The current release is **v0.6.3**.

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
- tenant-scoped asynchronous PDF jobs with idempotent submission, PostgreSQL
  leases and replayable events, cancellation, bounded retry, and true SSE
  reconnect from the durable event log;
- immutable PDF, evidence, crop, and deterministic ZIP-bundle storage through
  local or authenticated S3-compatible object-store adapters;
- Redis-compatible wake-up/fan-out and Qdrant derived-index adapters whose loss
  does not replace PostgreSQL or immutable object storage as authority;
- pinned ColSmol-256M integration and reproducibility evidence;
- immutable dependency/model/source contracts, container build evidence,
  runtime license policy, and hostile-PDF regression gates;
- Tokito Cloud upload/job integration and deterministic evidence-to-symbol
  contracts;
- a deployed private v0.6.3 API/worker data plane using PostgreSQL, SeaweedFS,
  Qdrant, and Valkey, plus a PostgreSQL catalog control plane in Tokito Cloud
  and integrity-checked immutable SQLite pack delivery to MCP;
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
- finish the standalone product beyond the shipped durable upload/job/SSE/
  evidence-bundle slice: symbol draft generation, review/correction,
  validation, explicit catalog contribution, the dedicated MCP surface, and a
  contract-equivalent self-hosted operator workflow;
- ship the authenticated hosted web review flow. DNS, TLS, and Cloudflare
  ingress for `dsvire.tokito.dev` are live and externally health-checked, but
  the hostname currently exposes the authenticated HTTP API—not a completed
  browser review product;
- install model-bound hybrid packs and prove Qdrant rebuild/reconciliation and
  cache-loss behavior under the production retrieval path. Production
  currently has no hybrid-query pack, so calibrated queries fail closed;
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

# Changelog

All notable changes to DS-ViRe are recorded here. Releases use immutable
`vMAJOR.MINOR.PATCH` container tags.

## Unreleased

## 0.4.0 - 2026-08-13

### PDF boundary and licensing

- Replace PyMuPDF with exact pypdfium2 5.12.1 plus strict pypdf preflight,
  bounded crop/text operations, explicit resource closure, and cache/adapter
  version bumps. Password-gated and repaired PDFs fail closed; readable
  permission-encrypted official datasheets remain supported.
- Remove the AGPL/commercial release decision and fail closed unless the
  installed pypdfium2 wheel retains its PDFium/native dependency license files.
- Replay the complete 30-document/18,810-pair text and OpenCLIP development
  comparators twice under PDFium and commit new renderer-bound evidence; old
  results remain historical and cannot silently authorize thresholds.

### Reproducible delivery

- Add a universal, cross-platform uv lock covering runtime, test, visual, and
  OpenCLIP environments, with frozen CI, release, and benchmark installs.
- Build the service from a digest-pinned Python base and a generated,
  hash-pinned runtime export; no package resolution or build backend runs in
  the container build.
- Add an executable lock-drift gate and documented dependency update workflow.
- Add strict static typing across the package and operational scripts, plus one
  fail-closed release verifier covering locks, source quality, tests, committed
  artifact contracts, packaging, and the hash-pinned runtime audit.

### Evaluation integrity

- Add source-free, content-addressed visual annotation review packets that bind
  exact registry, PDF, annotation, crop geometry, and rendered PNG hashes.
- Add strict review-decision schemas and an atomic promotion command that
  requires complete acceptance, an unchanged registry revision, and a real
  approved TokitoAI GitHub review whose author, timestamp, URL, and packet hash
  all match. Locally fabricated or partial review claims fail closed.

## 0.3.1 - 2026-08-11

### Security and correctness

- Reject PDFs that MuPDF had to structurally repair instead of treating
  reconstructed object relationships as authoritative engineering evidence.
- Bump the retrieval/cache policy to `dsvire-baseline@0.3.1`, preventing any
  previously cached evidence from a repaired document from bypassing the new
  admission rule.

## 0.3.0 - 2026-08-11

### Breaking contract

- Replace `dsvire.symbol-evidence.v1` with strict v2 verifier provenance.
  Ambiguous `verified` and `verify_confidence` fields are removed. Identity and
  region decisions now name their method, policy version, outcome, score, and
  score semantics; the deterministic baseline is explicitly heuristic and
  cannot claim calibrated visual verification.
- Require accepted pinout, table, and package evidence plus exact-identity
  region citations. Cached v1 manifests are rejected and rebuilt under
  `dsvire-baseline@0.3.0`.
- Preserve the fail-closed production posture: v0.3.0 emits attributable
  `text_layout_heuristic` evidence, while automated publication requires a
  separately calibrated `evidence_gated_visual` policy.

## 0.2.0 - 2026-08-11

### Correctness

- Treat caller-supplied manufacturer, MPN, and package as a hypothesis rather
  than evidence. Retrieval now abstains unless bounded PDF text independently
  contains the manufacturer and a token-bounded exact MPN associated with the
  requested package in one logical orderable-part row.
- Emit the grounded association as a third accepted `package` crop. Bounded
  wrapped rows are accepted, but adjacent variant rows, MPN prefix/suffix near
  misses, wrong manufacturers, and packages mentioned elsewhere are rejected.
- Bump the deterministic retrieval/cache policy to `dsvire-baseline@0.2.0`, so
  v0.1 packs that lack identity evidence cannot be reused.

### Evaluation and delivery

- Add a strict, hash-pinned development registry for three official TI
  datasheets without redistributing vendor PDF bytes.
- Add deterministic JSON metrics, document-family split leakage checks,
  reason-specific adversarial negatives, offline cache operation, and a hard
  zero-silent-wrong-identity gate.
- Require tagged releases to pass the real-PDF gate and publish its JSON result
  before building the immutable image.

### Compatibility and limitations

- The `dsvire.symbol-evidence.v1` JSON shape remains compatible, but hosted
  v0.2 output now contains three regions (`pinout`, `table`, and `package`)
  instead of two. Consumers must accept the already-defined `package` region.
- Text grounding is a deterministic safety gate, not calibrated visual EGVV.
  All three seed groups are development data from one vendor; held-out visual
  labels and the planned 500-document/2,000-query corpus remain open work.

## 0.1.1 - 2026-08-11

### Security

- Require a service bearer of at least 32 bytes in production and staging;
  unauthenticated operation now requires explicit development/test settings.
- Authenticate before buffering PDF request bodies.
- Parse and render untrusted PDFs in disposable spawned processes with hard
  wall-clock termination and Linux CPU, memory, file, descriptor, and core
  limits.
- Reject oversized candidate renders before native image allocation.
- Pin patched packaging tooling in the container and audit the declared runtime
  dependency graph in CI and release workflows.

### Reliability

- Bound processing admission before uploads are read and return stable overload,
  timeout, parser-abstention, and worker-failure responses.
- Remove worker scratch data after success, failure, timeout, and cancellation.
- Key evidence caches by input bytes, exact requested identity, and retrieval
  version; verify cached crop hashes and publish complete packs atomically under
  a cross-process lock.
- Verify persistent storage in the container parent before Uvicorn forks so
  unsafe startup exits nonzero.

### Delivery

- Add readiness, package-build, formatting, lint, dependency-audit, fail-closed
  container, authenticated worker, and tag-release gates.
- Publish only immutable version tags; the release workflow no longer publishes
  a mutable `latest` image.
- Add the living production-readiness audit. Exact part/package verification,
  calibrated visual verification, corpus benchmarking, durable jobs, and full
  Tokito upload orchestration remain explicit blockers rather than hidden
  claims.

## 0.1.0 - 2026-08-08

- Initial deterministic PDF-to-evidence baseline, hosted service image, frozen
  symbol-evidence contract, and TPS5430 generated-symbol proof.

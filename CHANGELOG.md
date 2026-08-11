# Changelog

All notable changes to DS-ViRe are recorded here. Releases use immutable
`vMAJOR.MINOR.PATCH` container tags.

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

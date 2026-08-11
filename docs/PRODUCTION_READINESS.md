# Production-readiness audit

**Status:** active; the project is not production-ready  
**Audit started:** 2026-08-11  
**Tracking epic:** [TokitoAI/tokito#336](https://github.com/TokitoAI/tokito/issues/336)

This is the evidence ledger for DS-ViRe and its Tokito integration. A green test
suite is evidence for the behavior those tests cover; it is not evidence that
the retrieval system, corpus, deployment, or user workflow is production-ready.

## Evidence baseline

| Evidence | Result | Scope / limitation |
|---|---|---|
| `python -m pytest -q` on Windows/Python 3.11 | 167 passed, 1 skipped on the multi-vendor tranche branch | Unit/fixture/API/evaluator tests; not corpus accuracy or load evidence |
| Local Uvicorn smoke, one worker | readiness 200; unauthenticated evidence request 401; authenticated malformed PDF 422; process and scratch cleaned | Windows process boundary; not Linux container/resource-limit evidence |
| Frozen dependency graph | Universal `uv.lock` SHA-256 `70c17dba...b3955` covers runtime/test/visual/OpenCLIP; runtime export SHA-256 `75add53d...0e4a` contains exact versions and artifact hashes; local drift gate, 178 tests, lint/format, no-isolation build, and locked-environment vulnerability audit pass | Docker boundary/build evidence must come from Linux CI because Docker is unavailable on this workstation; byte-identical image output has not yet been demonstrated |
| v0.2.0 release CI | Green: lint/format, 108 tests, package build/audit, hash-pinned real-PDF identity gate, Docker fail-closed + authenticated worker smokes, provenance/SBOM | Boundary, packaging, and small development-gate evidence; not representative corpus accuracy, load, or end-to-end user workflow evidence |
| Production v0.2.0 rollout | Exact GHCR digest `sha256:2e847017cd7fe3cc554d7ef37050b5940ee6e63886e065dfa11cce82791a73d3` deployed privately; readiness 200, unauthenticated evidence 401, authenticated malformed PDF 422, zero restarts; official TPS5430 exact identity accepted with three regions and wrong package abstained; timestamped config/data backup and v0.1.1 rollback retained | Boundary and one real-document smoke; rollback image retained but restore/rollback drill not yet executed |
| Corpus | Hash-pinned visual registry of eight official development PDFs across six manufacturer labels; obsolete schema-v1 generated artifacts were removed | Still not representative; all visual labels remain unreviewed development data and there are no held-out groups or checked-in vendor bytes |
| Exact-identity real-PDF gate (v0.2.0 release) | 3/3 exact identities emitted pinout, table, and package regions; 6/6 MPN/package negatives abstained with the expected reason; zero silent wrong-identity acceptances | All three groups are development data from one vendor, executed 2026-08-11; not a held-out accuracy or calibration estimate |
| v2 verifier-provenance real-PDF gate | 3/3 positives and 6/6 reason-matched negatives; zero silent wrong-identity acceptances; result schema `dsvire.identity-eval-result.v2` | Proves the breaking contract migration preserves the small development gate; it does not add visual verification or held-out calibration |
| v0.3.0 paired release/deployment | DS-ViRe release CI green (111 tests, lint/build/audit, Docker boundaries, 3-positive/6-negative real gate); exact DS-ViRe digest `sha256:3d4129179d8ba61761fc172a4f319ef4e556cd11581a2d6b657aaefc3511f6f6` deployed with tokito-ai v0.7.0 digest `sha256:084bae1ef433020e763fddb996f7f0be1b45350366ee8d60ff73045d80bae8f7`; both containers healthy with zero restarts; private health/readiness 200, unauthenticated extraction 401, authenticated malformed input 422, public API/MCP health 200; real TPS5430 v2 accepted by retrieval, wrong TSSOP package abstained, and the live publication endpoint rejected its heuristic-only evidence with 422 `evidence_rejected`; timestamped paired data/config backup and v0.2.0/v0.6.1 rollback images retained | Proves the versioned producer/consumer boundary and fail-closed publication policy in production; does not prove EGVV accuracy, restore success, rollback execution, load, or user upload orchestration |
| v0.3.1 repaired-PDF release/deployment | Release CI green (113 tests, lint/format, build/audit, 3-positive/6-negative real gate, Docker boundaries, provenance/SBOM); exact digest `sha256:cbcdff9bc60eda7608b28e020b359ddf6d16b4d01165381d9384d5be4c1a6626` deployed privately; service version/readiness 200, healthy with zero restarts; generated truncated-xref PDF rejected 422 with the stable repair error; official TPS5430 emitted v2 under `dsvire-baseline@0.3.1`, wrong TSSOP package abstained; public AI/MCP health 200; backup `/opt/tokito/backups/20260812T001600Z` validated, immediate v0.3.0 rollback retained, stale backups removed, zero dangling images, 35 GiB host space free | Proves this repair-path gate and deployment; broader malformed/scanned/rotated/parser-differential corpus, restore drill, and load evidence remain open |
| OpenCLIP visual-encoder candidate | Exact 605,143,316-byte LAION ViT-B-32 safetensors artifact pinned by commit/SHA-256. Two local Windows runs and clean GitHub runs `31538248265` / `31538257537` (attempt 2) all produced score digest `dae68875ad4952fdc7e96d35c893fb8ccb22a8239e61d8cbd5b2d5c95bccb0ff`; both GitHub artifact checksums validate; clean runtimes 5.05 s / 7.07 s, peak RSS 1.485 GB / 1.485 GB, external cost $0; 163 tests pass and the resolved extended environment has no known audited vulnerabilities. Run `31538257537` attempt 1 correctly failed closed after three TI CDN hash mismatches and emitted no result artifact. | Reproducible candidate comparison and source-integrity evidence, but not an acceptable identity verifier: wrong-variant mean similarity is close to positive and wrong-view mean is higher than positive; seed remains unreviewed single-vendor development data |
| First multi-vendor visual tranche | Five official, hash-pinned non-TI development families and 34 cases were manually contact-sheet inspected. Text-layout score digest `982c6350...e06f`: 0.480 s, 10.42 docs/s, 69.7 MiB peak RSS. RapidOCR score digest `90af1349...fc6d`: 127.96 s, 0.039 docs/s, 630.3 MiB peak RSS. RapidOCR positive/wrong-variant means were 0.790/0.484. Full compact export and chart are committed. | Useful adversarial and operability evidence only; annotations are agent-seeded/unreviewed, no threshold was fitted, and wrong-package/wrong-figure separation remains unsafe |
| Retrieval implementation | PyMuPDF text blocks + deterministic heading/pin-token heuristics | No layout model, visual embedding, reranking, OCR scan path, or benchmark |
| End-to-end product pieces | Evidence schema, extractor, compiler, ingestion store, MCP generated-symbol reads, Desktop MPN resolve exist across repositories | No authenticated user upload/job orchestration from Tokito Cloud to DS-ViRe and through publication |
| Container validation on this workstation | Not run: Docker CLI is unavailable | CI container evidence is required before merge |

## Severity rules

- **P0:** unsafe publication/corruption/auth behavior or a blocker to trustworthy use.
- **P1:** serious correctness, reliability, security, integration, or reproducibility gap.
- **P2:** important production capability or maintainability improvement.
- **P3:** optimization or polish after the system is trustworthy.

`Resolved` means a linked change and its stated verification exist. It does not
mean the broader workstream is complete.

## Findings

| ID | Severity | Status | Finding | Required evidence to resolve |
|---|---:|---|---|---|
| DSV-001 | P0 | Resolved in v0.1.1 | Hosted authentication was fail-open when `DSVIRE_SERVICE_TOKEN` was empty. | Startup-failure, unauthorized-request, and container tests with documented explicit local-only override. |
| DSV-002 | P0 | Partial in v0.2.0: [#338](https://github.com/TokitoAI/tokito/issues/338), [#341](https://github.com/TokitoAI/tokito/issues/341) | v0.2.0 adds fail-closed manufacturer presence, token-bounded exact-MPN matching, logical-row package association, a package crop, synthetic near-miss tests, and a three-document development gate. It still lacks representative held-out variant evaluation and OCR/visual identity evidence. | Representative variant tests, explicit package evidence, identity reconciliation, calibrated abstention, and zero silent wrong-variant publications in the release evaluation set. |
| DSV-003 | P0 | Partial: [#338](https://github.com/TokitoAI/tokito/issues/338), [#350](https://github.com/TokitoAI/tokito/issues/350), [#356](https://github.com/TokitoAI/tokito/issues/356) | Evidence v2 removes ambiguous `verified`/`verify_confidence`, names the heuristic method/policy/outcome, and prevents heuristic scores from claiming calibrated-probability semantics. tokito-ai v0.7.0 rejects heuristic-only evidence from automated publication. Deterministic split-safe policy/metric and strict annotation-registry contracts distinguish similarity from probability, prevent abstain-all from passing, require reviewed provenance, and bind adapter scores to registry-owned labels. Source-hash-checked text/layout, rendered-pixel RapidOCR, and hash-pinned OpenCLIP visual-encoder comparators now exist and bind implementations/dependencies/models. OpenCLIP reproduced its score digest but failed to separate exact-identity/orientation near misses well enough for selection; this prevents a popularity-based model choice. The executable runner records deterministic score identity plus latency, throughput, peak RSS, and external cost while keeping unreviewed development outputs ineligible for policy fitting. The 30-family annotations, a selected calibrated policy, and held-out EGVV evidence remain absent. | Calibrated held-out results, adversarial near-miss set, and wrong-figure rate at or below the SLO. |
| DSV-004 | P1 | Resolved in v0.1.1 | Untrusted PDF parsing ran inside the API process with no job admission bound or killable timeout. | Subprocess isolation, kernel limits, hard timeout/cancellation, bounded admission, cleanup, overload and crash tests. |
| DSV-005 | P1 | Resolved in v0.1.1 | Concurrent requests wrote directly into the same pack directory and failures could leave partial artifacts. | Identity/version keyed cache, lock, staging directory, atomic publication, integrity recheck, concurrent regression test. |
| DSV-006 | P1 | Partial: [#342](https://github.com/TokitoAI/tokito/issues/342), [#350](https://github.com/TokitoAI/tokito/issues/350), [#357](https://github.com/TokitoAI/tokito/issues/357), [#358](https://github.com/TokitoAI/tokito/issues/358) | Strict identity and visual provenance registries enforce group-level split leakage checks, download-only policy, hash verification, deterministic metric semantics, and release artifacts. A common bounded, atomic downloader and executable text-layout/RapidOCR runner produce reproducible comparator artifacts from exact source bytes. The visual registry contains 55 explicitly unreviewed cases across eight development families and six manufacturer labels. Local contact sheets and content-addressed review packets bind the registry, source, annotation revision, geometry, and rendered crop bytes. Review promotion requires complete acceptance plus an API-verified TokitoAI GitHub approval matching reviewer, timestamp, URL, and packet digest; partial, rejected, stale, or locally fabricated decisions fail closed. The first five-family multi-vendor export records score identity, speed, throughput, memory, and cost. No current agent-seeded annotation has been promoted. The 500-document/2,000-query corpus, held-out groups, actual independent reviews, legal review, and scheduled release-policy artifacts are still missing. | Reproducible provenance registry; dev/test splits; legal review; baseline runners; published metric artifacts. |
| DSV-007 | P1 | Partial in v0.3.1: [#348](https://github.com/TokitoAI/tokito/issues/348) | Parser-repaired documents now fail closed before evidence publication, with a generated truncated-xref regression proving cleanup. Scan, rotation, enormous PDF, duplicate/revision, partial-download variants, and parser differential paths still lack a versioned robustness corpus. | Versioned robustness corpus plus failure/recovery and fuzz/property evidence. |
| DSV-008 | P1 | Open | Tokito Cloud has DS-ViRe deployment variables and downstream ingestion routes but no real user upload/job orchestration, durable queue, cancellation, or status API. | Authenticated end-to-end upload-to-Desktop test with restart, retry, idempotency, cancellation, and partial-failure coverage. |
| DSV-009 | P1 | Open | No durable asynchronous index job model, checkpoints, deduplication registry, retry/backoff policy, or horizontal worker coordination exists. | Queue/storage design, migrations, worker leases, resumable integration tests, and load/failure benchmarks. |
| DSV-010 | P1 | Open | No structured pipeline telemetry, stage timings, trace propagation, queue depth, resource metrics, confidence distribution, or cost accounting exists. | Redacted structured logs, metrics/traces, dashboards/alerts, and an incident-debug exercise. |
| DSV-011 | P1 | Partial via [#359](https://github.com/TokitoAI/tokito/issues/359) | A universal uv lock now covers runtime, test, visual, and OpenCLIP graphs. CI, release, and manual benchmark jobs reject lock/export drift and use frozen installs through a version- and commit-pinned uv setup. The service image uses a digest-pinned Python base plus a generated hash-pinned runtime export and performs no dependency or build-backend resolution. Release images already request provenance and an SBOM. License policy and byte-identical independent image-build evidence remain absent. | Enforced license policy and two clean independent builds producing the same content digest. |
| DSV-012 | P1 | Open | Backup/restore, pack retention/garbage collection, migration, deployment rollback, and disaster-recovery procedures are unspecified and untested. | Documented procedures plus restore and rollback drills with recovery objectives. |
| DSV-013 | P1 | Resolved in DS-ViRe v0.3.0 / tokito-ai v0.7.0 | Evidence v2 requires accepted pinout, table, and package regions plus identity grounding provenance. The producer, canonical Rust contract, extractor context policy, publication gate, cross-repository tests, paired immutable releases, and live fail-closed deployment are complete. Desktop and MCP consume published catalog records rather than parsing evidence bundles, so they required no wire migration. | Versioned contract decision implemented by every producer/consumer with cross-repository contract tests. |
| DSV-014 | P2 | Open | CI lacks formatting/type/static-analysis gates and the local verifier is fixture-specific rather than a release-wide aggregate gate. | Pinned lint/type/build checks and one release command that validates all fixtures, schemas, artifacts, and benchmark thresholds. |
| DSV-015 | P2 | Open | The baseline API is synchronous per request and persists query artifacts locally; lifecycle, quotas, tenant isolation, and object-store ownership are not defined. | Ownership ADR, tenant/authz tests, quotas, lifecycle policy, and production storage integration. |

## Production gate matrix

| Area | Current verdict | Completion evidence |
|---|---|---|
| Accuracy and calibration | Missing | Held-out corpus metrics, error analysis, confidence calibration, regression thresholds |
| Determinism | Partial | Byte-identical compiler fixture exists; retrieval/cache reproducibility needs corpus evidence |
| Security | Partial | Service boundary hardening underway; parser, model/tool, dependency, tenant, and deployment threat model remains |
| Resilience and recovery | Missing | Durable jobs, restart/resume, retry, backup/restore, rollback drills |
| Observability | Missing | Structured logs, metrics, traces, dashboards, alerts, cost and confidence telemetry |
| Scalability and efficiency | Missing | Load tests and CPU/GPU/storage/latency Pareto against documented SLOs |
| Maintainability | Partial | Frozen schemas/tests exist; contract drift, locking, typing, and release gate remain |
| Reproducibility | Partial | Dependency/model/source locks and deterministic benchmark identities exist; corpus completion and independent byte-identical image proof remain |
| Deployment | Partial | Container/Compose exist; staging, rollback, resource policy, and recovery are unproven |
| Tokito workflow | Partial | Downstream pieces exist; upload/job orchestration and true user E2E are absent |

## Decision log

1. **2026-08-11 — keep PDF parsing outside the API process.** PDF bytes are
   untrusted, parsing is CPU-heavy native code, and thread timeouts cannot stop a
   wedged parser. A disposable spawned process supplies a kill boundary while
   Linux resource limits constrain common exhaustion paths.
2. **2026-08-11 — authentication fails closed.** Private-network placement is
   defense in depth, not authentication. Local insecure mode requires two
   explicit settings and is never valid in production/staging.
3. **2026-08-11 — do not call the heuristic verifier EGVV.** It is a useful
   deterministic baseline but cannot prove visual or exact-variant correctness.
4. **2026-08-11 — caller identity is a hypothesis, not evidence.** The hosted
   baseline must abstain unless bounded PDF text independently contains the
   manufacturer and associates the exact token-bounded MPN with the requested
   package in the same logical orderable-part row. This reduces silent near-miss publication;
   it does not replace OCR,
   visual verification, or held-out calibration.

## Next burn-down order

1. Resolve DSV-002/003/013 before allowing automated catalog publication from
   live uploads.
2. Establish the legal corpus registry, annotation protocol, split policy, and
   executable baseline benchmark (DSV-006/007).
3. Build durable Tokito Cloud orchestration and E2E tests (DSV-008/009).
4. Add observability, load/SLO evidence, dependency locking, and recovery drills.

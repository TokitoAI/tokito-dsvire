# Tokito datasheet-to-symbol product pipeline

**Status:** product architecture contract  
**Updated:** 2026-08-17

This document defines how DS-ViRe evidence becomes a native, cataloged Tokito
symbol. The first production milestone is deliberately narrow, not a throwaway
implementation or a reduced architectural target.

The core rule is:

> Models interpret datasheet evidence. Deterministic code constructs symbols.

---

## 1. Responsibility boundaries

| Component | Owns | Does not own |
|---|---|---|
| `tokito-dsvire` | PDF ingest, region retrieval, typed evidence, provenance, visual verification | Symbol geometry, catalog publication, BOM identity |
| Symbol extraction worker | Evidence-to-`SymbolSpec`, reconciliation, confidence | Free-form symbol files, catalog writes |
| Tokito symbol compiler | Deterministic layout, canonical Tokito `Symbol`, `.tokito_sym` serialization | Datasheet retrieval, publication authorization |
| Catalog ingestion service | Validation, identity, revisioning, moderation, publication | LLM extraction |
| `tokito-mcp` | Unified search and resolution over official and generated symbols | Unauthenticated model-driven writes |
| Tokito Desktop | Placement, ephemeral resolved-symbol cache, schematic embedding | Catalog source-of-truth storage |

DS-ViRe stays independently useful and benchmarkable as figure-level retrieval.
Symbol generation is a downstream Tokito product built on its evidence contract.

---

## 2. End-to-end flow

```text
Upload datasheet or corpus
  -> register source, hash, manufacturer, MPN, package candidate
  -> check exact manufacturer + MPN + package in the Tokito catalog
  -> if a trustworthy symbol exists, resolve it normally
  -> otherwise index the datasheet with DS-ViRe
  -> retrieve pinout, pin-description table, package and supporting regions
  -> extract a constrained SymbolSpec
  -> reconcile independent evidence
  -> compile deterministic Tokito geometry
  -> serialize and parse-round-trip .tokito_sym
  -> validate semantics, geometry, provenance and identity
  -> publish a versioned generated catalog revision
  -> resolve through tokito-mcp's normal catalog surface
  -> place in Desktop and embed in the schematic document
```

The workflow is idempotent. Repeating the same source hash, exact part identity,
extractor version, and compiler version must resolve to the same generation job
or artifact revision rather than creating duplicate catalog entries.

---

## 3. Identity model

Do not collapse part identity, symbol geometry, and schematic persistence.

### 3.1 Part identity

`part_id` identifies a manufacturer component and package variant. It is used by
BOM, procurement, saved parts, and design validation. The durable natural key is
the normalized manufacturer plus exact MPN; package must be stored and checked
because suffixes commonly select materially different pinouts.

### 3.2 Catalog symbol identity

`library_id` / `symbol_id` identifies symbol geometry served by the catalog.
Generated symbols live in an explicit generated namespace and carry immutable
revision IDs. Names are presentation labels, not sufficient revision identity.

### 3.3 Schematic identity

When a symbol is placed, Tokito links the instance to both `part_id` and
`library_id`. The schematic embeds the resolved single-symbol `.tokito_sym`
definition in `SchematicDocument.lib_symbols`, preserving rendering and netlist
behavior if the catalog changes or is unavailable.

---

## 4. DS-ViRe evidence bundle

The generator receives typed evidence, never a raw unbounded PDF dump.

```json
{
  "schema_version": "dsvire.symbol-evidence.v2",
  "datasheet": {
    "id": "...",
    "content_sha256": "...",
    "manufacturer": "Texas Instruments",
    "mpn": "TPS5430DDAR",
    "package": "SO-PowerPAD-8"
  },
  "identity_verification": {
    "method": "exact_text_orderable_part",
    "policy_version": "dsvire.identity-text@2.0.0",
    "outcome": "accepted",
    "manufacturer_observed": true,
    "exact_mpn_observed": true,
    "package_associated": true,
    "evidence_region_ids": ["r_package_01"]
  },
  "regions": [
    {
      "region_id": "r_pinout_01",
      "type": "pinout",
      "page": 3,
      "bbox_norm": [0.08, 0.12, 0.92, 0.71],
      "crop_uri": "dsvire://pack/.../r_pinout_01.webp",
      "content_hash": "sha256:...",
      "verification": {
        "method": "text_layout_heuristic",
        "policy_version": "dsvire.region-text-layout@2.0.0",
        "outcome": "accepted",
        "score": 0.97,
        "score_semantics": "heuristic_evidence_strength"
      }
    }
  ],
  "retrieval": {
    "index_version": "dsvire-baseline@0.4.0",
    "model_ids": ["pdfium@754f2dc4fc47", "pypdf@6.7.0"],
    "query_ids": ["..."]
  }
}
```

Required evidence classes are:

1. Exact pin-number map or pinout figure.
2. Pin-description table.
3. Exact package/variant evidence.
4. Supporting functional text when electrical type is not explicit.

Missing or contradictory required evidence causes abstention or quarantine. A
single attractive pinout image is not enough to publish a product symbol.

---

## 5. SymbolSpec extraction

The extraction worker emits strict JSON under a versioned schema. Unknown fields
are rejected and all strings, arrays, and source payloads are bounded.

```json
{
  "schema_version": "tokito.symbol-spec.v1",
  "manufacturer": "Texas Instruments",
  "mpn": "TPS5430DDAR",
  "package": "SO-PowerPAD-8",
  "reference_prefix": "U",
  "pins": [
    {
      "number": "1",
      "name": "BOOT",
      "electrical": "passive",
      "style": "line",
      "group": "bootstrap",
      "unit": 1,
      "hidden": false,
      "confidence": 0.98,
      "evidence_region_ids": ["r_pinout_01", "r_pin_table_01"]
    }
  ],
  "properties": {
    "datasheet": "...",
    "description": "...",
    "footprint": "",
    "keywords": "buck regulator switching"
  }
}
```

The model may infer electrical semantics, groups, and units, but it does not emit
coordinates, S-expressions, SQL, catalog revisions, or publication commands.

### 5.1 Reconciliation

Reconciliation compares independently extracted pinout and table observations.
It verifies:

- exact package and MPN suffix;
- expected versus observed pin count;
- pin number and name agreement;
- aliases, repeated power pins, NC/reserved pins, and exposed pads;
- intentional duplicate pin numbers;
- evidence coverage for every published pin;
- confidence thresholds and unresolved conflicts.

Conflicts remain explicit. A verifier may adjudicate using the bounded source
crops, but unresolved conflicts never become silently selected values.

### 5.2 Electrical typing

Electrical types are constrained to Tokito's enum: input, output,
bidirectional, tri-state, passive, free, unspecified, power-in, power-out,
open-collector, open-emitter, and no-connect. Datasheet descriptions are the
authority; naming rules are only priors. Low-confidence classifications use
`unspecified` or block publication according to policy.

---

## 6. Deterministic Tokito symbol compiler

The compiler consumes a validated `SymbolSpec` and constructs
`tokito_catalog::symbol_format::Symbol` directly.

### 6.1 Layout rules

- Place positive supply pins at the top and ground/negative supply at the bottom.
- Place inputs, enables, clocks, reset, and configuration pins on the left.
- Place outputs on the right.
- Group bidirectional buses and GPIOs by functional bank with stable ordering.
- Preserve datasheet pin numbers as connectivity keys.
- Calculate body size from pin count, group count, and measured label width.
- Use Tokito electrical-grid spacing and inward-facing pin stubs.
- Add deterministic group separators or labels only when they improve readability.
- Add Reference, Value, Datasheet, Description, Footprint, MPN, Manufacturer,
  package, provenance, and generator metadata as canonical properties.

The symbol is a logical schematic representation. It is not a pixel trace of the
datasheet package drawing.

### 6.2 Determinism

The same normalized `SymbolSpec`, layout-policy version, and compiler version
must produce byte-identical canonical output and the same content hash. Sorting,
spacing, text measurement, float formatting, and default properties are pinned.

### 6.3 Multi-unit symbols

The product supports functional units and shared power units in the specification
and catalog model. Desktop currently places only unit 1; production completion
requires proper per-unit placement. Until then, valid multi-unit revisions are
marked unavailable for placement rather than flattened into electrically
incorrect single-unit symbols.

---

## 7. Native artifact and validation

The compiler serializes using Tokito's canonical writer to `.tokito_sym`. KiCad
compatibility is an interoperability property, not the product identity.

Publication validation includes:

1. `SymbolSpec` schema and bounded-input validation.
2. Pin/table/package reconciliation.
3. Construction of the canonical Tokito `Symbol`.
4. `.tokito_sym` serialization and parse round-trip.
5. Semantic comparison before and after round-trip.
6. Geometry, grid, label-overlap, and size-limit checks.
7. ERC-oriented electrical-type and connectivity checks.
8. Deterministic hash reproduction.
9. Render snapshot and human-readable evidence report.
10. Place, wire, save, reopen, and embedded-symbol integration tests.

No pin may disappear, change its connectivity number, lose provenance, or move
off the allowed electrical grid during compilation or serialization.

---

## 8. Catalog synchronization

### 8.1 Current state

`tokito-mcp` serves a read-only official `symbols.sqlite` artifact built from a
pinned upstream KiCad symbol tree. Tokito Cloud writes generated revisions to
its separate `generated.sqlite`; the MCP runtime validates published revisions
into a separate immutable generated catalog pack, atomically swaps complete
packs, and retains the last-known-good pack on refresh failure. Both served
catalogs are query-only. Tokito Desktop consumes the hosted MCP face, keeps only
an ephemeral resolved-symbol cache, and embeds the exact resolved symbol source
inside each saved schematic.

This is a valid single-host publication boundary, not the target collaborative
control plane. The current production catalog has no published generated
revision, and automated DS-ViRe publication remains disabled until its frozen
quality gates pass.

### 8.2 Product target

The hosted catalog resolves two provenance-preserving sources through one read
contract:

```text
official import revisions ─┐
                           ├─> Postgres catalog control plane
generated symbol revisions ┘              |
                                transactional publication
                                           |
                              verified immutable SQLite pack
                                           |
                     MCP / offline clients / release rollback
```

Postgres is the authoritative writer-side database for part and catalog
identity, immutable revisions, provenance, validation attempts, moderation,
publication/supersession, policy, audit, and a transactional outbox. Official
and generated revisions share schemas and read behavior while retaining exact
source and license provenance. Large canonical `.tokito_sym` artifacts,
reports, source PDFs, and evidence remain content-addressed in object storage;
Postgres stores their hashes and bounded references.

Generated symbols do not require a full container rebuild for every accepted
submission. A publication worker consumes committed outbox events, builds a
complete digest-addressed SQLite candidate, verifies schema/content/manifest
integrity, and atomically promotes it. `tokito-mcp` hot-reloads only complete
packs and keeps the last-known-good revision on failure. Neither DS-ViRe nor MCP
receives direct catalog-writer credentials.

Migration from `symbols.sqlite` plus writer-side `generated.sqlite` must import
exact revisions and hashes, dual-build/read-compare packs, and prove rollback,
backup/restore, and schema migration before writer authority moves.

### 8.3 Publication lifecycle

```text
draft -> validating -> verified -> published -> superseded
                    \-> quarantined
```

- `draft`: extraction complete but not trusted.
- `validating`: deterministic and integration checks are running.
- `verified`: checks passed; eligible for policy or human approval.
- `published`: visible through normal catalog resolution.
- `superseded`: retained for reproducibility but not the default revision.
- `quarantined`: conflicting, malformed, unsafe, or revoked.

Catalog revisions are immutable. Corrections create a new revision and preserve
the old artifact for schematics that already embed or reference it.

### 8.4 Write security

Generation writes use an authenticated internal ingestion API or worker identity,
not an unauthenticated public MCP tool. The service enforces authorization,
idempotency keys, payload limits, content hashes, audit events, rate limits,
malware-safe source handling, and explicit publication policy.

### 8.5 Cache and realtime boundary

A Redis-compatible service may accelerate bounded search responses, rate
limits, idempotency checks, cache-stampede locks, worker wake-ups, progress, and
SSE fan-out/replay. It is never the only copy of a job, permission, revision,
evidence record, audit event, or publication decision. Durable job/lease state
and the publication outbox remain in Postgres. Cache keys bind tenant, model,
index, policy, and catalog versions; complete cache loss must be recoverable by
reconciliation without semantic data loss.

---

## 9. MCP and Desktop behavior

Existing catalog tools continue to work across official and generated symbols.
The product adds exact manufacturer/MPN/package resolution and provenance/status
reads without forcing clients onto a separate generated-symbol transport.

Useful catalog capabilities are:

- search symbols across official and published generated revisions;
- resolve exact manufacturer + MPN + package;
- retrieve a fully resolved symbol body;
- retrieve provenance, generation version, and publication status;
- find electrically/package-compatible candidates;
- report that generation is pending, quarantined, or unsupported.

Desktop receives the same resolved-symbol wire shape, converts it through the
existing `convert_symbol` path, links the placed instance to `part_id` and
`library_id`, and embeds the exact `.tokito_sym` revision in the schematic.

### 9.1 Standalone product behavior

DS-ViRe also exposes contract-equivalent CLI, authenticated HTTP, MCP, hosted
web, and self-hosted surfaces. A private user can upload a permitted datasheet,
follow a durable asynchronous job, inspect or correct an evidence-backed draft,
and download a deterministic bundle without publishing to Tokito's catalog.

The bundle contains the canonical `.tokito_sym`, supported interchange output,
part/package metadata, validation report, exact datasheet citations, evidence
hashes or permitted crops, and a machine-readable provenance manifest. Public
catalog contribution is a separate explicit authenticated action. Uploads,
evidence, drafts, indexes, and bundles are private by default and tenant-scoped.

See [`SERVICE_ARCHITECTURE.md`](SERVICE_ARCHITECTURE.md) for service topology,
store ownership, cache semantics, deployment profiles, and migration gates.

---

## 10. Product completion gates

The first vertical slice is complete only when an unsupported datasheet can:

1. Be uploaded, hashed, probed, and indexed.
2. Resolve exact manufacturer, MPN, and package identity.
3. Produce independently verified pinout and pin-table evidence.
4. Compile a native deterministic Tokito symbol.
5. Create or link the real Tokito `part_id`.
6. Publish a versioned generated catalog revision through authenticated ingestion.
7. Resolve through the normal `tokito-mcp` catalog surface.
8. Place, wire, save, reopen, and render in Tokito Desktop.
9. Embed the exact definition into the schematic.
10. Audit every pin back to exact datasheet evidence.
11. Produce the same deterministic private bundle through CLI/API/web and the
    Tokito client path.
12. Survive API, worker, Redis, and host restart without losing authoritative
    job, evidence, or publication state.

Scale work then expands corpus coverage, model quality, queue throughput,
moderation operations, multi-unit placement, robustness, and benchmark depth.
Those are product increments, not reasons to replace the architecture with a
one-off path.

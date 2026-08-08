# Hackathon vertical slice plan

**Status:** implementation plan
**Date:** 2026-08-08
**Scope:** first end-to-end vertical slice defined by [`TOKITO_SYMBOL_PIPELINE.md`](TOKITO_SYMBOL_PIPELINE.md) §10 (product completion gates)

This document is the shared plan across `tokito-dsvire`, `tokito-catalog`, `tokito-ai`, `tokito-mcp`, and `tokito`. DS-ViRe stays a spec today. Every other repo gets the code needed to accept a DS-ViRe evidence bundle, produce a `.tokito_sym`, publish it, and place it in Tokito Desktop.

Production quality applies — see the parent bible and the pipeline doc. No mocked returns, no placeholder pins, no "TODO wire later" in shipping code paths. If a stage can't ship completely, cut its scope and note the gap explicitly.

---

## 1. Slice definition

One MPN travels the full path:

```
DS-ViRe evidence bundle
  -> tokito-ai symbol-extractor       (LLM + reconciliation -> SymbolSpec)
  -> tokito-catalog symbol-compiler   (SymbolSpec -> Symbol -> .tokito_sym)
  -> tokito-ai catalog-ingestion      (authenticated publish)
  -> tokito-mcp generated store       (versioned, immutable revision)
  -> tokito desktop                   (resolve -> place -> embed)
```

For the hackathon:

- **Bundle input** for the slice is a fixture (checked-in JSON) that matches the `dsvire.symbol-evidence.v1` shape. DS-ViRe itself does not need to be running.
- **MPN** targeted: pick one part with a clean pinout and pin-description table. `STM32H743VIT6` (LQFP100) or `TPS5430DDAR` are both suitable; final pick lives in the fixture.
- **Success:** the part is placed and wired in Tokito Desktop from a fresh cold start with only the seeded generated revision.

Product completion gates 1–10 from the pipeline doc are the acceptance list. Gate 1 (upload/hash/probe/index) is stubbed to "load fixture bundle" for today.

---

## 2. Contracts (shared types)

All shared schemas are frozen in [`CONTRACTS.md`](CONTRACTS.md). The Rust definitions live in **`tokito-catalog`** so every consumer (`tokito-ai`, `tokito-mcp`, `tokito` desktop) can depend on a single crate. New public module: `tokito_catalog::pipeline`.

- `pipeline::evidence` — `EvidenceBundle` (`dsvire.symbol-evidence.v1`)
- `pipeline::spec` — `SymbolSpec` (`tokito.symbol-spec.v1`)
- `pipeline::identity` — `PartId`, `LibraryId`, `SymbolRevisionId`
- `pipeline::status` — `PublicationStatus`, `Provenance`

Everything is `#[serde(deny_unknown_fields)]` and versioned by `schema_version` string. Schema constants and validation live in this module.

---

## 3. Per-repo work

### 3.1 `tokito-catalog` — shared types + deterministic compiler

New public modules under `src/pipeline/`:

- `pipeline/mod.rs` — schema versions, re-exports
- `pipeline/evidence.rs` — `EvidenceBundle` type
- `pipeline/spec.rs` — `SymbolSpec` type + strict validation
- `pipeline/identity.rs` — identity types
- `pipeline/status.rs` — publication lifecycle enum

New crate-internal module `src/compiler/`:

- `compiler/mod.rs` — `compile(&SymbolSpec) -> Result<Symbol, CompileError>`
- `compiler/layout.rs` — layout policy (§6.1 of pipeline doc): top = power-in, bottom = ground/power-out, left = inputs/enables/clock/reset, right = outputs, group buses, body sized from pin count + label widths, electrical-grid spacing.
- `compiler/determinism.rs` — pinned sort orders, float formatter, canonical property order
- `compiler/tests.rs` — golden byte-identical `.tokito_sym` for one fixture; snapshot compare

Compiler outputs are directly usable by the existing `src/symbol_format/writer.rs`. No new serializer.

**Determinism gate:** compiling the same normalized SymbolSpec + layout-policy version + compiler version must produce byte-identical `.tokito_sym`. Enforced by test.

### 3.2 `tokito-ai` — extractor + ingestion API

Two new workspace crates under `tokito-ai/crates/`:

**`symbol-extractor`** (new)
- Consumes `EvidenceBundle` from `tokito-catalog::pipeline::evidence`.
- Calls Claude via the existing `llm-gateway` crate. Uses **Claude Sonnet 4.6** for extraction (production-quality reconciliation), **not Haiku**.
- Prompts constrained with `SymbolSpec` JSON schema; response parsed via strict serde. Reprompts once on validation failure, then abstains.
- Two independent extractions per bundle (pinout vs pin-description table), reconciliation compares them: pin-count, pin-numbers, names, aliases, NC/reserved, exposed pads. Conflicts kept explicit, never silently resolved.
- Emits `SymbolSpec` when confidence + coverage thresholds pass; emits `ExtractionAbstained { reasons }` otherwise.
- Fully deterministic given same evidence + same model snapshot (temperature 0, seed set where supported).

**`catalog-ingestion`** (new)
- New crate; may reuse `crates/api` axum stack.
- `POST /v1/generated/ingest` — authenticated (existing JWT). Accepts a `SymbolSpec` + parent `EvidenceBundle`. Compiles via `tokito-catalog::compiler`, validates round-trip parse, computes revision hash, writes to the generated store (see §3.3), emits audit event.
- `GET /v1/generated/:revision_id` — read the revision manifest (used by `tokito-mcp` and diagnostics).
- Enforces: auth (existing), idempotency key on the `(source_hash, extractor_version, compiler_version)` triple, bounded payload sizes, malware-safe source handling (already partial in existing endpoints), rate limit.
- The **generated symbol store** for the hackathon is a new SQLite database `generated.sqlite` next to `tokito-ai.sqlite` in `TOKITO_AI_DATA_DIR`. Schema in `migrations/`. Immutable rows, unique on revision id.

The `api` crate wires the new routes and enforces auth via existing middleware.

### 3.3 `tokito-mcp` — unified read surface

Extend `crates/symbols` and `crates/server`.

`crates/symbols`:
- New table `generated_symbol` in schema.sql, mirroring `symbol` but adding `revision_id`, `part_id`, `provenance_json`, `status`, `content_hash`, `published_at`.
- New table `part_registry` keyed by `(manufacturer, mpn, package)` returning `part_id`.
- New resolver in `resolver.rs`: `resolve_by_mpn(manufacturer, mpn, package)` returns the published revision (or `Pending` / `Quarantined` status).
- Search widened to include published generated symbols with a `source` marker (`official` | `generated`).

`crates/server`:
- Two new MCP tools:
  - `resolve_by_mpn` — exact identity resolve.
  - `get_symbol_provenance` — return provenance JSON + publication status.
- `get_symbol` continues to work for both official and generated (dispatch by `lib` prefix, e.g. `generated:*`).
- REST mirrors for both new tools.
- **Read-only guarantee is preserved.** MCP does not accept writes. Generated rows are populated by a new sidecar workflow, `pack --generated`, that reads from `tokito-ai`'s `generated.sqlite` and merges into the served `symbols.sqlite`. In production this becomes a live sync; for the hackathon slice, a manual pack run demonstrates the loop.

### 3.4 `tokito` (Desktop) — receive generated symbols

Most of the change is verifying that the existing `CatalogGrounding` MCP client accepts generated `lib` values. Additions:

- Wire the new MCP `resolve_by_mpn` tool through the existing MCP client (`src/services/cloud.rs` / `catalog` path).
- Store both `part_id` and `library_id` on placed instances (identity model §3 in pipeline doc). Confirm current place flow persists both.
- Embed the exact `.tokito_sym` revision body into `SchematicDocument.lib_symbols` on placement (should already happen; add a test).
- New UI affordance: "Add part by MPN" that calls `resolve_by_mpn` and places on success, surfaces status/pending otherwise. This is the only new UI element for the slice.

### 3.5 `tokito-dsvire` — docs only today

- This doc + [`CONTRACTS.md`](CONTRACTS.md) freeze the interface DS-ViRe must eventually produce.
- The hackathon fixture bundle is checked in under `tokito-dsvire/fixtures/evidence/<mpn>.json` (data only; no code). This is the only new content in `tokito-dsvire`.

---

## 4. Execution order (concurrency-friendly)

Stages that can run in parallel are grouped.

**Wave A — foundation (blocks everything downstream):**
1. `tokito-catalog::pipeline` module (shared types) — small, precise.
2. `tokito-catalog::compiler` skeleton + one passing determinism test.

**Wave B — parallel after A:**
3. `tokito-ai::symbol-extractor` crate.
4. `tokito-mcp` schema + resolver + new MCP tools (backed by empty generated table initially).
5. `dsvire/fixtures/evidence/<mpn>.json` fixture authored from real datasheet (human-checked crops).

**Wave C — parallel after B:**
6. `tokito-ai::catalog-ingestion` (needs 1, 2, 3).
7. `tokito-mcp::pack --generated` sync path (needs 4 and the ingestion output shape).
8. `tokito` Desktop `resolve_by_mpn` wire (needs 4).

**Wave D — end-to-end:**
9. Run the slice: fixture → extract → compile → ingest → sync → resolve in Desktop → place → save/reopen.

---

## 5. What is explicitly out of scope for today

- The real DS-ViRe retrieval stack (fixture stands in).
- Multi-unit symbol placement in Desktop (per pipeline doc §6.3, valid multi-unit revisions are marked unavailable rather than placed as broken single units).
- Live datasheet corpus, benchmark corpus, moderation UI.
- Multiple MPNs in one publish batch.
- Automatic invalidation across running Desktop instances (manual reconnect is fine for the demo).
- Public-facing rate limiting / abuse prevention beyond the auth+idempotency+size checks.

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Compiler determinism drift | Pin sort orders, float formatter, canonical property order — enforce with byte-identical golden test in `tokito-catalog::compiler::tests`. |
| Extractor hallucination | Strict SymbolSpec schema (`deny_unknown_fields`), two independent extractions + reconciliation, abstain rather than guess. |
| Storage split (`tokito-ai` writes, `tokito-mcp` reads) drifts | For the hackathon: single manual `pack --generated` step reads `generated.sqlite` and rebuilds served artifact. Documented as a real sync-service TODO, not faked. |
| Desktop assumes only `official` libs | Explicit `lib` prefix `generated:*`; add unit test at MCP client boundary. |
| Time crunch | Wave A is the only single-critical-path chunk. Everything else parallelizes. Cut the "Add part by MPN" UI to CLI-driven test if time-boxed. |

---

## 7. Success criteria for demo

- Cold start Tokito Desktop, empty schematic.
- User (or a scripted click) requests MPN `X`.
- Desktop calls `resolve_by_mpn`, gets a published generated revision.
- Symbol is placed with correct pin count, labels, electrical types, package property, MPN property, and datasheet URL.
- Save the file, close, reopen — schematic renders identically from the embedded `.tokito_sym`.
- `get_symbol_provenance` on the placed part returns the DS-ViRe evidence region IDs.

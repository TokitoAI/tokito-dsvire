# Pipeline contracts

**Status:** versioned production boundary; v2 current
**Updated:** 2026-08-13
**Home for Rust definitions:** `tokito-catalog::pipeline`

This file is the source of truth for the wire types between DS-ViRe, the extractor, the compiler, the ingestion service, and the MCP read surface. Every producer and consumer must reject unknown fields.

The held-out retrieval authoring boundary is separately defined by the strict
`retrieval_authoring_{packet,submission,review,seal}_v1.schema.json` schemas in
`scripts/schema/`. Their semantic validator additionally enforces page/source
bindings, exact intent and hard-negative coverage, natural-query constraints,
distinct GitHub humans, immutable review provenance, canonical digests, and the
final score-access authorization bit. See `evaluation/README.md` for the
leakage-safe operator sequence.

Rust: all types derive `Serialize, Deserialize` with `#[serde(deny_unknown_fields)]`, plus `Debug, Clone, PartialEq, Eq` where applicable. `schema_version` is a required `&'static str` constant per type; deserialization rejects mismatched versions.

---

## 1. `dsvire.symbol-evidence.v2`

Emitted by DS-ViRe query. Consumed by `tokito-ai::symbol-extractor`.

```json
{
  "schema_version": "dsvire.symbol-evidence.v2",
  "datasheet": {
    "id": "st-ds-h743-r09",
    "content_sha256": "b2f1...c3",
    "manufacturer": "STMicroelectronics",
    "mpn": "STM32H743VIT6",
    "package": "LQFP100"
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
      "page": 42,
      "bbox_norm": [0.08, 0.12, 0.92, 0.71],
      "crop_uri": "dsvire://pack/xxxxxxxx/r_pinout_01.webp",
      "content_hash": "sha256:aa...",
      "verification": {
        "method": "text_layout_heuristic",
        "policy_version": "dsvire.region-text-layout@2.0.0",
        "outcome": "accepted",
        "score": 0.97,
        "score_semantics": "heuristic_evidence_strength"
      },
      "caption": "Figure 7. LQFP100 pinout (top view)"
    },
    {
      "region_id": "r_pin_table_01",
      "type": "table",
      "page": 44,
      "bbox_norm": [0.10, 0.08, 0.90, 0.94],
      "crop_uri": "dsvire://pack/xxxxxxxx/r_pin_table_01.webp",
      "content_hash": "sha256:bb...",
      "verification": {
        "method": "text_layout_heuristic",
        "policy_version": "dsvire.region-text-layout@2.0.0",
        "outcome": "accepted",
        "score": 0.94,
        "score_semantics": "heuristic_evidence_strength"
      }
    },
    {
      "region_id": "r_package_01",
      "type": "package",
      "page": 2,
      "bbox_norm": [0.08, 0.18, 0.92, 0.36],
      "crop_uri": "dsvire://pack/xxxxxxxx/r_package_01.webp",
      "content_hash": "sha256:cc...",
      "verification": {
        "method": "text_layout_heuristic",
        "policy_version": "dsvire.region-text-layout@2.0.0",
        "outcome": "accepted",
        "score": 1.0,
        "score_semantics": "heuristic_evidence_strength"
      }
    }
  ],
  "retrieval": {
    "index_version": "dsvire-baseline@0.4.0",
    "model_ids": ["pdfium@754f2dc4fc47", "pypdf@6.7.0"],
    "query_ids": ["q_pinout", "q_pin_table"]
  }
}
```

**Rules**

- At least one `pinout`, one `table`, and one `package` region with
  `verification.outcome: accepted` are required for symbol evidence produced by the hosted
  baseline.
- `datasheet.manufacturer` must occur in bounded PDF text. The exact requested
  MPN must match with alphanumeric token boundaries and must occur in the same
  logical orderable-part row as the requested package. Bounded wrapped
  continuation lines are allowed, but adjacent part rows must never be combined. The
  `package` region is the crop containing that association; callers do not
  become evidence merely by supplying the identity fields.
- `regions[*].type` ∈ `{pinout, package, timing, curve, block, app_circuit, table, other}`.
- `bbox_norm` is `[x0, y0, x1, y1]` in `[0,1]`, each strictly `x0 < x1`, `y0 < y1`.
- `crop_uri` is opaque to the extractor; it is passed through to provenance.
- `content_hash` is `sha256:<hex>`; used as region provenance.
- `text_layout_heuristic` must use `heuristic_evidence_strength`; it cannot use
  `calibrated_probability`. Only an `evidence_gated_visual` method backed by
  held-out calibration may use the latter semantics.
- Publication policy must explicitly allow a verification method. An accepted
  heuristic result never silently satisfies a visual-verification policy.
- `retrieval.model_ids` is required for reproducibility; extractor persists it into the SymbolSpec's provenance block.

**Rust surface** (`tokito_catalog::pipeline::evidence`)

```rust
pub const SCHEMA_VERSION: &str = "dsvire.symbol-evidence.v2";

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EvidenceBundle {
    pub schema_version: String,
    pub datasheet: DatasheetIdent,
    pub identity_verification: IdentityVerification,
    pub regions: Vec<Region>,
    pub retrieval: RetrievalMeta,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DatasheetIdent {
    pub id: String,
    pub content_sha256: String,
    pub manufacturer: String,
    pub mpn: String,
    pub package: String,
}

// Region, RegionType, RetrievalMeta follow the JSON above.
```

---

## 2. `tokito.symbol-spec.v1`

Emitted by extractor. Consumed by compiler.

```json
{
  "schema_version": "tokito.symbol-spec.v1",
  "manufacturer": "STMicroelectronics",
  "mpn": "STM32H743VIT6",
  "package": "LQFP100",
  "reference_prefix": "U",
  "pins": [
    {
      "number": "1",
      "name": "PE2",
      "electrical": "bidirectional",
      "style": "line",
      "group": "gpio_e",
      "unit": 1,
      "hidden": false,
      "confidence": 0.98,
      "evidence_region_ids": ["r_pinout_01", "r_pin_table_01"]
    }
  ],
  "properties": {
    "datasheet": "https://www.st.com/resource/en/datasheet/stm32h743vi.pdf",
    "description": "High-performance MCU, Arm Cortex-M7, 480 MHz, 2 MB Flash",
    "footprint": "",
    "keywords": "mcu cortex-m7 stm32"
  },
  "provenance": {
    "evidence_datasheet_id": "st-ds-h743-r09",
    "evidence_content_sha256": "b2f1...c3",
    "extractor_version": "tokito-ai.symbol-extractor@0.1.0",
    "model": "claude-sonnet-4-6",
    "extracted_at": "2026-08-08T07:12:00Z"
  }
}
```

**Rules**

- `reference_prefix` ∈ common set (`U`, `Q`, `D`, `R`, `C`, `L`, `Y`, `J`, `K`, `SW`, ...). Extractor picks by device family; compiler passes through.
- `pins[*].electrical` matches the KiCad-derived enum already in `tokito_catalog::model::PinElectrical`: `input | output | bidirectional | tri_state | passive | free | unspecified | power_in | power_out | open_collector | open_emitter | no_connect`.
- `pins[*].style` ∈ `tokito_catalog::model::PinStyle` (`line`, `inverted`, `clock`, `inverted_clock`, `input_low`, `output_low`, ...). Default `line`.
- `pins[*].unit` is `1` unless the device has multiple functional units (per pipeline doc §6.3, multi-unit is not placeable in the hackathon slice, but the spec still admits it).
- `pins[*].confidence` ∈ `[0.0, 1.0]`. Pins with `confidence < 0.6` cause the whole spec to be abstained (compiler refuses).
- `pins[*].evidence_region_ids` must reference regions in the source `EvidenceBundle`. Non-empty.
- Duplicate `number` values are allowed only when tagged as intentional jumpers (surfaced through `SymbolFlags.duplicate_pin_numbers_are_jumpers`).
- Unrecognised or missing pin numbers vs. the package's expected pin count is a hard reconciliation failure.

**Rust surface** (`tokito_catalog::pipeline::spec`) — pin fields lift directly to `tokito_catalog::model::Pin` at compile time.

---

## 3. Identity types

```rust
// tokito_catalog::pipeline::identity

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Hash)]
#[serde(deny_unknown_fields)]
pub struct PartId {
    pub manufacturer_norm: String, // NFC + lowercased + whitespace-collapsed
    pub mpn: String,               // exact case-sensitive
    pub package: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Hash)]
pub struct LibraryId {
    pub lib: String,   // "generated:stmicroelectronics" or "official:MCU_ST_STM32H7"
    pub name: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Hash)]
pub struct SymbolRevisionId(pub String); // content-hash-derived, e.g. "gen_sha256_ab12..."
```

`PartId` normalization rules are enforced by a single constructor `PartId::new(manufacturer, mpn, package)` that returns `Result<Self, IdentityError>`.

---

## 4. Publication status

```rust
// tokito_catalog::pipeline::status

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PublicationStatus {
    Draft,
    Validating,
    Verified,
    Published,
    Superseded,
    Quarantined,
}
```

For the hackathon slice, ingestion goes `Draft -> Validating -> Verified -> Published` in a single request when all checks pass; no human moderation loop is inserted. Failure paths route to `Quarantined` with a reason string.

---

## 5. Provenance record

Persisted alongside every published generated revision. Returned by `get_symbol_provenance`.

```json
{
  "revision_id": "gen_sha256_ab12...",
  "part_id": {
    "manufacturer_norm": "stmicroelectronics",
    "mpn": "STM32H743VIT6",
    "package": "LQFP100"
  },
  "library_id": {
    "lib": "generated:stmicroelectronics",
    "name": "STM32H743VIT6"
  },
  "evidence": {
    "datasheet_id": "st-ds-h743-r09",
    "content_sha256": "b2f1...c3",
    "region_ids": ["r_pinout_01", "r_pin_table_01"]
  },
  "pipeline": {
    "extractor_version": "tokito-ai.symbol-extractor@0.1.0",
    "compiler_version": "tokito-catalog.compiler@0.1.0",
    "layout_policy_version": "layout@0.1.0",
    "extractor_model": "claude-sonnet-4-6",
    "dsvire_index_version": "dsvire-index@0.1.0",
    "dsvire_model_ids": ["colqwen2-v1.0", "doclayout-yolo@abcd"]
  },
  "status": "published",
  "published_at": "2026-08-08T07:15:00Z",
  "content_hash": "sha256:cc..."
}
```

`content_hash` is the sha256 of the canonical serialized `Symbol` body (the exact bytes written to `.tokito_sym`, minus timestamps). Two runs of the pipeline on the same evidence must produce the same `content_hash`.

---

## 6. Errors

All errors surface as `thiserror` variants in `tokito_catalog::pipeline::error`. Notable:

- `EvidenceRejected { reason }` — missing required regions, verified=false, unknown region type.
- `ExtractionAbstained { reasons: Vec<String> }` — extractor could not produce a spec above thresholds.
- `SpecInvalid { field, reason }` — validation failure inside `SymbolSpec`.
- `Reconciliation { conflicts: Vec<Conflict> }` — pin table vs. pinout disagreement.
- `CompilerFailed { reason }` — layout could not be constructed.
- `IdentityCollision { existing_revision }` — same `(source_hash, extractor_version, compiler_version)` already published (idempotency hit — return existing, do not error at the API level).

---

## 7. Versioning

- Any change to the JSON shape bumps `schema_version` (e.g. `v1` -> `v1.1` for additive, `v2` for breaking).
- Consumers pin exact versions; unknown versions are rejected. Version tables live in `tokito_catalog::pipeline` constants.
- Never repurpose a field name. Add a new one, deprecate the old, remove after a full release cycle.

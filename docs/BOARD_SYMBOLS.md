# Board scans to private symbol drafts

The optional Tokito app action sends only an exact reviewed board-context
revision to `POST /v1/platform/board-symbols?context_revision=...`. It uses a
tenant API key, not the service administrator token. Camera frames, microphone
audio, ROI geometry, caller-selected URLs and inferred part IDs are not inputs.

The service generates **private schematic drafts**, using the existing isolated
PDF worker and standalone SVG/JSON compiler. It does not publish a catalog
revision, create a native `.tokito_sym`, generate 3D models, or change board
placement. The frozen automated publication gate still applies independently.

## Audit the real app dataset

```powershell
dsvire plan-board-symbols --dataset C:/path/to/tokito-app-dataset `
  --board nxp_frdm_mcxn236_board --out board-symbol-plan.json
```

Board family keys come from `data/photo-model/source-bundles.json`. The audit
retains source file hashes, source/specimen relations, schematic inventory
candidates and unidentified visual seeds. It reports zero generation-ready
parts: the dataset's partial component labels are not exact part identities or
complete electrical specifications. MCXN947 is never substituted for MCXN236.
No model training, dataset labeling changes or accuracy claims are made.

## Operator setup and review

Install permitted dataset/source files under `<DSVIRE_DATA_DIR>/board-dataset`.
Keep licenses and private vendor documents private. Establish exact specimen,
board revision, component registration, manufacturer/MPN/package, catalog
resolution, datasheet provenance and the complete physical pin set through
human review. A library reference or generic package resemblance is insufficient.

Provision a tenant through the existing platform-init workflow. A tenant must
have its own PostgreSQL-issued key. Store its approved binding at:

```text
<DSVIRE_DATA_DIR>/board-bindings/<tenant UUID>/<SHA256 of exact context revision>.json
```

The context revision is the phone's admitted board-reference revision, not a
board-family guess. Bindings contain at most eight major components. Split
larger reviewed contexts into separately reviewed batches in a future version;
this version rejects larger bindings.

Required binding fields:

```json
{
  "schema_version": "dsvire.board-binding.v1",
  "context_revision": "EXACT_PHONE_CONTEXT_REVISION",
  "board_family": "nxp_frdm_mcxn236_board",
  "board_revision": "REVIEWED_PHYSICAL_REVISION",
  "review_status": "pending",
  "reviewed_by": "",
  "dataset_sources": [],
  "specimen_match": {"status": "pending", "path": "", "sha256": ""},
  "parts": []
}
```

This template deliberately cannot execute. Copy the audit's exact `sources`
array into `dataset_sources`. Attach a hash-bound, reviewed exact specimen
correspondence record under the dataset root. Set `review_status=approved`,
`specimen_match.status=reviewed_exact` and identify the actual human reviewer
only after review. This server-owned approval cannot be supplied by the mobile
request or a visual model.

Each part requires `reference`, `manufacturer`, `mpn`, `package` and
`catalog_status`. A `resolved` entry must name its `catalog_revision` and is
skipped. A `missing` entry requires the complete `expected_pin_numbers` string
array and a `datasheet` object with relative `path`, `sha256` and optional
`source_url`. Keep the catalog resolution snapshot current when installing a
binding; this version does not perform a live MCP catalog search.

PDF identity must independently agree, and the returned unique pin numbers must
equal the complete reviewed pin set. Unknowns and discrepancies abstain. File
paths cannot escape the dataset root. A changed audited metadata file invalidates
the binding. The authenticated endpoint caps the entire operation at 75 seconds,
shares PDF admission limits, and cancels child work on disconnect or timeout.
Multi-component requests can time out; lower the reviewed batch size rather
than raising resource bounds indiscriminately.

## Phone flow

In **Local models → Missing board symbols**, save the HTTPS service origin and
tenant API key. The app uses secure storage and restores the optional service
without making offline bench use depend on it. No credentials enter the board
reference or its synced observations.

Load the reviewed, authored placement-bound board reference through the existing
operator context workflow, then register the correct physical board in AR.
Choose **Generate missing symbols**, confirm the displayed model/revision and
authorize sending that context to the configured service. Results explicitly
distinguish existing symbols, private drafts, abstentions and unavailable work.
Full draft JSON, SVG and citations are retained in app-private `symbol-drafts/`;
the review dialog shows pin names/types and citation counts. It does not place
symbols on the PCB or claim that draft pin facts have passed human review.

Cancellation, leaving the activity, or losing registration discards late results
and cancels transport. Drafts never replace the admitted assembly context.

## Current dataset limitation

No reviewed production board binding was manufactured for this change. The
current photographed boards still need exact specimen/component correspondence
and datasheet review. The synthetic tests exercise the complete generation
boundary; they are not evidence of board recognition or real-part accuracy.

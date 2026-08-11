# Identity evaluation registry

This directory records provenance and labels, not vendor PDF bytes. Each source
is downloaded from the official HTTPS URL into an operator-selected cache and
must match its reviewed SHA-256 before DS-ViRe parses it.

Run the current development slice:

```bash
python scripts/evaluate_identity.py \
  --cache-dir .cache/dsvire-eval \
  --json-out identity-eval.json
```

Use `--offline` after the hashes are cached. The command exits nonzero for a
source hash change, a positive retrieval failure, an unexpected abstention
reason, or any silently accepted wrong identity/package.

Tagged releases run this command before image publication and upload the JSON
result as an immutable workflow artifact. Normal pull-request CI stays offline;
unit tests exercise registry and metric semantics with generated PDFs.

## Split and leakage policy

- `document_group` owns every revision and identity from one datasheet family.
  A group may never occur in more than one split.
- `development` documents may guide implementation and threshold choices.
- `evaluation` groups are held out until a versioned policy is frozen. Moving a
  previously inspected development group to evaluation is prohibited.
- Multiple exact orderable identities may share one document hash only when
  they keep the same group and split.
- Vendor sources marked `download_only` are never committed or redistributed.

If a mutable vendor URL changes bytes, the downloader refuses to cache them and
the gate stops. Do not overwrite a reviewed hash silently: inspect the new
revision and add or update its registry entry in the same `document_group` and
split. Held-out `evaluation` labels and hashes are immutable after first use.

The initial three TI documents are all `development`; their 3/3 positive and
6/6 expected-abstention result is a regression gate, not a held-out accuracy or
calibration estimate. Scale the registry toward the planned 500-document,
2,000-query corpus without changing result-field meanings; new metrics require
a new result schema version.

## Visual-verifier calibration contract

`dsvire.visual_metrics` is the model-independent policy boundary for the EGVV
benchmark tracked in TokitoAI/tokito#350. Candidate adapters emit one reviewed
case score plus its document group, split, and ground-truth error class. The
metric engine then:

- rejects duplicate cases and document-family leakage across development,
  calibration, and evaluation;
- selects a threshold only from the calibration split, maximizing positive
  coverage subject to zero accepted wrong-package/variant cases and the 2%
  verified-path wrong-visual ceiling;
- freezes the model digest, preprocessing version, dataset digest, metric
  version, threshold, score semantics, and coverage floor into a hashed policy;
- applies that policy unchanged to evaluation and reports coverage, wrong-case
  counts/rates, and AURC;
- reports Brier score and 10-bin ECE only when an adapter explicitly supplies
  probabilities. Similarity scores never receive probability metric names.

The abstain-all threshold is a valid safe output but cannot pass the default
positive-coverage gate. This module is evaluation infrastructure, not proof
that any current model is calibrated and not authorization to enable automated
publication. The versioned multi-vendor annotations and candidate adapters must
land and meet the held-out gate first.

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

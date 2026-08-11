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

`dsvire.visual_registry` owns the corresponding annotation contract. It binds
each source to an HTTPS revision and SHA-256, keeps document families in one
split, requires reviewed calibration/evaluation labels with reviewer/time
provenance, validates normalized page regions and view orientation, and makes
positive/wrong-package/wrong-variant identity relationships explicit. Every
document must include positive pinout, table, and package regions plus at least
one adversarial case. Adapter output is only a map of qualified case IDs to
scores; labels and splits come from the registry, and missing or injected cases
are rejected. This prevents a model runner from grading its own predictions.

The first comparator is `dsvire.visual_adapters.TextLayoutAdapter`. It scores
only text extracted inside each registered crop, verifies exact source bytes,
rejects repaired/encrypted/out-of-range documents, and binds its normalized
implementation source plus exact PyMuPDF version into adapter metadata. It is
deliberately declared as `similarity`, never visual or calibrated probability.
Its purpose is to quantify what a real OCR/visual candidate improves and expose
cases (for example graphical pin maps) where the text baseline abstains.

`dsvire.visual_adapters.RapidOcrAdapter` is the first pixel-reading candidate.
It renders the registered crop at the bounded production DPI and runs the
bundled RapidOCR/ONNX Runtime models on those pixels, independent of the PDF
text layer. Metadata binds the adapter implementation, every bundled ONNX model
byte, and exact RapidOCR/ONNX Runtime/PyMuPDF versions. OCR confidence only
attenuates a structural similarity score; it remains `similarity`, not a
calibrated probability. Install it with `tokito-dsvire[visual]`. CI and tagged
release verification install the visual extra, run a real-engine rendered-crop
smoke, and audit the fully resolved environment.

The RapidOCR adapter fixes ONNX CPU inference to one intra-op and one inter-op
thread and quantizes its similarity output to five decimal places. This removes
the observed one-millionth scheduling jitter from score artifacts; the adapter
and preprocessing IDs version that contract. Quantization does not make the
score a probability or relax any held-out acceptance threshold.

`dsvire.visual_adapters.OpenClipAdapter` is the first maintained visual-encoder
comparator. It renders the same bounded crops and compares them with a
registry-derived image/text prompt using OpenCLIP ViT-B-32. The LAION model
revision, 605,143,316-byte safetensors artifact, SHA-256, license, and
download-only handling are frozen in `visual_models.v1.json` and asserted
against the adapter constants in CI. The adapter accepts only that local,
hash-verified file and never asks OpenCLIP or Hugging Face to download weights.
Inference is CPU-only, single-threaded, and five-decimal quantized. Its cosine
mapping remains `similarity`; it is not a calibrated probability and cannot
by itself verify an alphanumeric orderable-part identity.

Two independent Windows CPU executions over the three-family seed produced the
same score digest,
`dae68875ad4952fdc7e96d35c893fb8ccb22a8239e61d8cbd5b2d5c95bccb0ff`.
The cached run took 6.13 seconds at 1.05 GB peak RSS; the first run took 76.20
seconds at 772 MB peak RSS because first-use CPU kernel setup dominated its
first document. Positive mean similarity was 0.65395, while wrong-variant mean
similarity was 0.64261 and wrong-view mean similarity was higher at 0.66903.
This is decisive rejection evidence for standalone identity/orientation use,
not a threshold candidate. OCR/exact-token reconciliation remains necessary.

`visual_registry.v1.json` seeds this contract with the same three hash-pinned
official TI development documents used by the identity gate. It records 21
cases: pinout/table/package positives plus wrong-package, wrong-variant,
wrong-view, and wrong-figure cases per family. Crop coordinates were generated
from the v0.3.1 baseline and inspected for internal consistency, but every entry
is deliberately marked `unreviewed`. Therefore none may enter calibration or
evaluation, and this seed is not accuracy evidence. PDF bytes remain excluded.

Run a frozen comparator against the registry:

```bash
python scripts/evaluate_visual.py \
  --cache-dir .cache/dsvire-eval \
  --adapter text-layout \
  --json-out visual-text-layout.json

python scripts/evaluate_visual.py \
  --cache-dir .cache/dsvire-eval \
  --adapter rapidocr \
  --json-out visual-rapidocr.json

python -m pip install -e '.[test,visual,openclip]'
python scripts/evaluate_visual.py \
  --cache-dir .cache/dsvire-eval \
  --adapter openclip \
  --json-out visual-openclip.json
```

Use `--offline` once the exact source hashes are cached. The runner binds labels
from the registry after inference, hashes the registry, adapter implementation,
model/preprocessing identity, and score map into `score_sha256`, and records
per-document latency, throughput, peak process RSS, and external cost. Timing
and memory fields are deliberately excluded from the deterministic score hash.
Fresh downloads retry a hash mismatch at most three times to tolerate an
inconsistent vendor CDN edge, but accept only the registered digest. Cached
corruption and every other source-contract violation still fail immediately.

The committed seed is unreviewed development data. These outputs are comparator
and operations evidence only: `eligible_for_policy_fitting` remains false, no
threshold may be calibrated from them, and they cannot authorize publication.

Repository operators can run the same network/model benchmark from GitHub's
**visual benchmark** workflow by selecting a frozen adapter. The workflow is
manual-only, uses least-privilege read permissions and pinned actions, downloads
hash-checked vendor PDFs only into ephemeral runner storage, and uploads only
the commit-bound result JSON plus its SHA-256 checksum for 30 days. It does not
cache or publish vendor PDFs. A successful workflow proves reproducibility and
operability; it does not change the registry's review status or calibration
eligibility.

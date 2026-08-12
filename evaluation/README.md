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

The identity registry's initial three TI documents are all `development`; their 3/3 positive and
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
Clean GitHub runs `31538248265` and `31538257537` (attempt 2) independently
reproduced that digest with valid uploaded checksums at 5.05/7.07 seconds and
1.485/1.485 GB peak RSS. Attempt 1 of the latter received a different TPS5430
PDF hash from the TI CDN on all three bounded attempts and correctly produced
no benchmark artifact; the registered source hash was not relaxed.

`visual_registry.v1.json` now contains twenty hash-pinned official development
documents across ten manufacturer labels: the original three TI families plus
ATmega328P, MCP3008, AP2112, ESP32, RP2040, PCA9685, BME280, NCP1117, and
PCF8574, ISL1208, CAT24C32, MCP2561/2, MCP23017/23S17, MCP2515, MCP4725,
MCP73831, and W5500. Its 139 cases include positive
pinout/table/package evidence and explicit package, variant, view, and figure
adversaries. All twenty exact-hash families were rendered into local contact
sheets and inspected under the repository owner's explicit authorization. The
source-free agent decision packets accept all 139 cases and identify the
reviewer as `agent:codex-gpt5`; this is not independent human annotation. Every
family remains development-only, cannot enter calibration/evaluation, and is
not held-out accuracy evidence. PDF and contact-sheet bytes remain excluded
from Git.

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

uv sync --locked --extra test --extra visual --extra openclip
python scripts/evaluate_visual.py \
  --cache-dir .cache/dsvire-eval \
  --adapter openclip \
  --json-out visual-openclip.json
```

Render local review sheets from the same hash-pinned bytes before accepting an
annotation change:

```bash
python scripts/render_visual_review.py \
  --cache-dir .cache/dsvire-eval \
  --out-dir .cache/dsvire-review
```

### Independent annotation review

`scripts/review_visual_annotations.py` is the promotion boundary for human
annotation review. Exporting a packet renders the local contact sheets and
records the exact registry, source PDF, annotation revision, normalized crop,
and rendered PNG hashes. Vendor PDF and crop bytes stay local:

```bash
python scripts/review_visual_annotations.py export \
  --cache-dir .cache/dsvire-eval \
  --out-dir .cache/dsvire-review \
  --packet-out evaluation/reviews/<packet>.packet.json \
  --document-id <document-id>
```

Independent review uses two pull requests so provenance is not circular. The
first PR contains only the source-free packet. The named human independently
renders and inspects every case, then submits an **Approve** review whose body
contains `DSVIRE_REVIEW_PACKET_SHA256=<packet_sha256>`. After that PR is merged,
create the complete decision from the immutable GitHub review metadata:

```bash
python scripts/review_visual_annotations.py attest \
  --packet evaluation/reviews/<packet>.packet.json \
  --reviewer github:<reviewer> \
  --reviewed-at <GitHub-submitted-at> \
  --review-url <GitHub-pull-request-review-url> \
  --out evaluation/reviews/<packet>.decision.json

python scripts/review_visual_annotations.py apply \
  --packet evaluation/reviews/<packet>.packet.json \
  --decision evaluation/reviews/<packet>.decision.json \
  --out evaluation/visual_registry.v1.json
```

`apply` makes a bounded GitHub API request (optionally authenticated with
`GITHUB_TOKEN`) and requires the API review to be `APPROVED`, authored by the
declared reviewer, timestamp-identical, URL-identical, and bound to the packet
digest in its body. It then requires every case to be accepted and the current
registry/source/case/annotation revision to match exactly before atomically
writing a reviewed registry. Missing, duplicate, rejected, tampered, stale, or
agent-self-asserted decisions fail closed. The packet and decision schemas live
in `scripts/schema/`; neither tool grants review status merely because an agent
generated the initial annotations.

When the repository owner explicitly authorizes an agent audit, use the
separate `dsvire.visual-agent-review-decision.v1` contract and `apply-agent`.
It records an `agent:<id>` reviewer, the authorization note, exact source/case
counts, excluded findings, and one decision per packet-bound crop. This path
does not claim human or independent review. On 2026-08-12, the owner authorized
that audit for packet `27ed6141...25bf`: 13 exact-hash documents and 90 crops
were accepted after visual inspection. ATmega328P was initially excluded because
its proposed table crop showed oscillator settings rather than pin evidence.
The crop was corrected to Table 13-3 (Port B alternate functions), then packet
`4b9bac85...832a` accepted ATmega328P, MCP2561/2, and MCP23017/23S17: three
exact-hash documents and 21 crops. The registry now has agent-attributed review
for the first sixteen families without claiming independent human review. A
third packet, `61543b7a...c96a`, accepts the seven MCP2515 cases after its first
pinout crop was rejected for clipping two leads and regenerated.

The first non-TI tranche has a compact, source-free evidence export at
[`results/multivendor-development-2026-08-12.json`](results/multivendor-development-2026-08-12.json).
On Windows/Python 3.11, the post-correction refresh processed the five documents
with text-layout in 0.527 s (9.49 documents/s, 69.4 MiB peak RSS);
single-threaded RapidOCR took 116.12 s (0.043 documents/s, 632.8 MiB peak RSS).
RapidOCR raised positive mean similarity from 0.763 to 0.796 and reduced
wrong-variant mean similarity from
0.600 to 0.484, but wrong-package and wrong-figure separation remains unsafe.
These are comparator measurements, not accuracy or calibration claims.

![Multi-vendor development benchmark](../docs/assets/multivendor-development-benchmark.svg)

Use `--offline` once the exact source hashes are cached. The runner binds labels
from the registry after inference, hashes the registry, adapter implementation,
model/preprocessing identity, and score map into `score_sha256`, and records
per-document latency, throughput, peak process RSS, and external cost. Timing
and memory fields are deliberately excluded from the deterministic score hash.
Fresh downloads retry a hash mismatch at most three times to tolerate an
inconsistent vendor CDN edge, but accept only the registered digest. Cached
corruption and every other source-contract violation still fail immediately.

The committed seed is owner-authorized agent-audited development data, not
independent human annotation or held-out evaluation. These outputs are
comparator and operations evidence only: `eligible_for_policy_fitting` remains
false, no threshold may be calibrated from them, and they cannot authorize
publication.

Repository operators can run the same network/model benchmark from GitHub's
**visual benchmark** workflow by selecting a frozen adapter. The workflow is
manual-only, uses least-privilege read permissions and pinned actions, downloads
hash-checked vendor PDFs only into ephemeral runner storage, and uploads only
the commit-bound result JSON plus its SHA-256 checksum for 30 days. It does not
cache or publish vendor PDFs. A successful workflow proves reproducibility and
operability; it does not change the registry's review status or calibration
eligibility.

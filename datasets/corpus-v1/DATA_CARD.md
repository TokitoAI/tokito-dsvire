# DS-ViRe local corpus v1

Created: 2026-08-17T10:21:26.187127Z

## Purpose

Local research corpus for DS-ViRe datasheet layout, retrieval, and evidence-model training. This is data, not a benchmark result and not evidence that a model is calibrated.

## Contents

- 635 unique, structurally readable official-manufacturer PDFs
- 25,324 vendor-datasheet pages
- 736,296,404 vendor PDF bytes
- 23 manufacturers
- 457 catalog-identity-supported training candidates
- 178 layout-only candidates
- 2,393 human-annotated DocLayNet auxiliary pages in one verified shard
- 27,717 total usable page records across domain and auxiliary data

corpus.jsonl is authoritative. identity-supervised-candidates.jsonl and
layout-only-candidates.jsonl are views over it. SHA256SUMS.txt binds every
training record to its content-addressed PDF under raw/.

## Provenance

Candidates came from the immutable Tokito/KiCad-derived symbol catalog whose
SHA-256 is c1b6b1ed481e97f2a761468b8d76448a27d845ddbb1edf517683c1102fce38a1. Acquisition retained requested/final
URLs, timestamp, HTTP metadata, catalog identities, content SHA-256, byte size,
page count, PDF metadata, category, and manufacturer.

Only allowlisted official manufacturer hosts were eligible. Files were rejected
for network/HTTP failure, off-allowlist redirects, invalid PDF magic,
encryption, structural parse failure, resource bounds, exact duplicates, or
overlap with sealed evaluation material.

## Split and leakage policy

Every vendor record is training_candidate. No automatic development split is
claimed because content-hash partitioning cannot prevent near-family leakage.
The pre-existing DS-ViRe calibration/evaluation registry remains the sealed
evaluation boundary. Before acquisition, 72
known evaluation URLs and 72 hashes were
excluded. Post-acquisition audits checked requested URLs, redirect targets,
content hashes, source stems, and normalized identity markers. One redirected
URL overlap and two family-marker overlaps were removed. The final audit reports
zero URL, hash, and family-marker overlap.

A future development split must be assigned by reviewed manufacturer/family
clusters, not random document hash.

## Rights and redistribution

Vendor PDF bytes are local research material. They must not be committed,
uploaded, or redistributed. Manifests, source URLs, hashes, aggregate statistics,
and original annotations may be published after review. Vendor terms require
review before commercial training or model publication.

## Label limitations

Catalog symbol names are weak identity supervision, not human ground truth.
identity-supervised-candidates.jsonl requires at least one exact normalized
catalog-token hit in a bounded text sample. This does not prove package,
revision, or every orderable suffix. layout-only-candidates.jsonl is for
layout/self-supervised work, not exact-part identity training.

No region boxes, query judgments, EGVV labels, or pin-row labels are asserted by
the raw vendor corpus.

## Auxiliary layout data

The verified DocLayNet v1.1 shard under auxiliary/doclaynet/shards contains
2,393 human-annotated pages. Its SHA-256 is
f0e668f5aa5b0ecda49236413a6da1e9172846ec0178584533eb349ec6d0fdce, matching the upstream LFS digest. The shard contains
only financial_reports, so it is generic layout pretraining data—not
semiconductor evidence or DS-ViRe evaluation. The other 28 train shards are not
present. Upstream attribution and CDLA-Permissive-1.0 license text are retained.

## Document fingerprints

Every vendor PDF was independently text-extracted after acquisition.
document-fingerprints.jsonl records normalized text digests, bounded head/tail
digests, text coverage, URL-family seeds, and family cluster IDs. All 635
documents fingerprinted without errors; no exact normalized-text duplicates
were found. One 12-page document has no extractable text and remains in the
layout-only visual cohort.

The automatic URL-family seeds are not semantic family ground truth. They are
all singletons in this tranche, so a future development split still requires
reviewed manufacturer/family clustering.

## Files

- candidates.jsonl: acquisition candidate ledger
- corpus.jsonl: accepted vendor training manifest
- identity-supervised-candidates.jsonl: stronger weak-label view
- layout-only-candidates.jsonl: non-identity view
- quarantine.jsonl: failed, duplicate, or excluded attempt ledger
- report.json: aggregate and integrity audit
- SHA256SUMS.txt: vendor PDF digest ledger
- source-review.json: admitted, rejected, and unavailable public sources
- auxiliary/doclaynet/train-source-manifest.json: all upstream train shards and LFS digests
- auxiliary/doclaynet/train-acquisition-report.json: exact locally present auxiliary data

Source PDFs are content-addressed as raw/<sha-prefix>/<sha256>.pdf.

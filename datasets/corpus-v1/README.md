# DS-ViRe corpus v1

Corpus v1 is a provenance-controlled acquisition registry for training and
data-development work. It is not the benchmark registry and it does not change
the sealed calibration or evaluation sets.

## Snapshot

| Cohort | Documents/pages | Intended use |
|---|---:|---|
| Official manufacturer datasheets | 635 documents / 25,324 pages | Domain pretraining and reviewed annotation |
| Catalog identity supported | 457 documents | Weak identity supervision |
| Layout only | 178 documents | Layout and self-supervised objectives |
| DocLayNet auxiliary shard | 2,393 pages | Generic layout pretraining only |
| Total | 27,717 page records | Training candidates, never benchmark evidence |

The accepted vendor PDFs span 23 manufacturers and 10 coarse product
categories. Every record binds the requested and final source URLs, acquisition
metadata, byte count, page count, content SHA-256, source-catalog digest,
manufacturer, symbols, category, label tier, and split status.

## Files

- [`corpus.jsonl`](corpus.jsonl) — authoritative accepted-document registry.
- [`identity-supervised-candidates.jsonl`](identity-supervised-candidates.jsonl) — records with bounded exact catalog-token evidence.
- [`layout-only-candidates.jsonl`](layout-only-candidates.jsonl) — records without sufficient identity evidence.
- [`document-fingerprints.jsonl`](document-fingerprints.jsonl) — normalized-text and family-seed audit ledger.
- [`SHA256SUMS.txt`](SHA256SUMS.txt) — expected private-cache paths and document digests.
- [`report.json`](report.json) — acquisition, coverage, and integrity summary.
- [`source-review.json`](source-review.json) — admission decisions for considered public datasets.
- [`DATA_CARD.md`](DATA_CARD.md) — intended use, limitations, leakage policy, and rights boundary.
- [`auxiliary/doclaynet`](auxiliary/doclaynet/) — upstream attribution, license, shard registry, and local-acquisition report. The 1.1 GB shard itself is obtained from the canonical upstream dataset.

The authoritative `corpus.jsonl` digest is
`9a08b1298e89cf088aed8fa902cc5e093130c66bcd551e89003a4ea7c81c69cb`.

## Contributing data

Open an issue before acquiring a large source. A contribution should add
metadata and original annotations—not third-party PDF bytes—and must provide:

- an official source URL and the URL after redirects;
- retrieval time, byte size, page count, and SHA-256;
- manufacturer, exact part/family candidates, and category;
- the source terms reviewed and the permitted use asserted;
- structural validation outcome and any quarantine reason;
- an explicit check against all sealed evaluation URLs, hashes, and part-family markers;
- a label tier that does not claim stronger identity supervision than the evidence supports.

Do not create random document-level train/development splits. Related part
families and document revisions must remain in one reviewed family cluster.

## Obtaining bytes

Resolve `source_url` from `corpus.jsonl`, review the current publisher terms,
and download into a private content-addressed cache matching
`raw/<sha-prefix>/<sha256>.pdf`. Verify the bytes against the manifest before
use. Source sites and terms can change; the manifest is provenance, not a grant
of rights or a guarantee that a URL will remain live.

The DocLayNet auxiliary data is independently licensed under
CDLA-Permissive-1.0. Its committed upstream manifest binds all 29 shard names,
sizes, LFS digests, Xet hashes, and source revisions; corpus v1 used and verified
only the shard named by `train-acquisition-report.json`.

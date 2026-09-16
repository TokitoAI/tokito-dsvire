# Security

Report vulnerabilities privately to the maintainers via GitHub Security Advisories on this repository:

https://github.com/TokitoAI/tokito-dsvire/security/advisories/new

Do not open public issues for undisclosed security problems.

## Notes for this project

- Treat OCR text, captions, and PDF-derived strings as untrusted input.
- Do not commit credentials, signed datasheet URLs, or private packs.
- Manufacturer PDFs may be copyrighted; do not publish redistributed corpora.
- Training and evaluation downloads must be HTTPS, hash-pinned, and public.
  Private, loopback, link-local, and credentialed URLs are refused. Corpus
  fetches must remain on official manufacturer hosts after redirects.
- Detector weights are verified by size and SHA-256 at load; they are never
  downloaded as a side effect of detection.
- The ColSmol extra stays pinned to `transformers==5.5.0` / `accelerate==1.14.0`
  to match the hash-bound adapter. CI currently ignores PYSEC-2026-3929 and
  PYSEC-2026-3804 on that extra only. Do not use that extra for untrusted
  model hubs or production training.

## Hosted-service boundary

- Production and staging fail startup unless `DSVIRE_SERVICE_TOKEN` is set to a
  secret of at least 32 bytes. Unauthenticated mode requires both an explicit
  development/test environment and `DSVIRE_ALLOW_INSECURE_DEV=true`.
- The container's parent process validates authentication configuration and
  proves the data volume writable before Uvicorn forks. Child startup failure is
  not relied upon as the container failure signal.
- Authenticate before accepting or buffering PDF bodies. Keep the service on a
  private network; Tokito Cloud is the public authorization and rate-limit
  boundary.
- PDF parsing and rendering execute in disposable subprocesses. Linux workers
  receive CPU, address-space, output-file, descriptor, and core-dump limits;
  every platform receives a hard wall-clock timeout and process termination.
- Per-process admission is bounded. Deployments must additionally apply
  container memory/CPU/PID limits and an aggregate edge/request limit.
- Job scratch directories are private and deleted after success, failure,
  timeout, or cancellation. Persistent packs are written under a keyed lock and
  atomically published.
- Parser/model output is evidence, never authority. It cannot invoke tools,
  publish catalog data, or bypass the downstream schema, reconciliation,
  compiler, and authenticated ingestion gates.

The remaining threat-model and production gaps are tracked in
[`docs/STATUS.md`](docs/STATUS.md).

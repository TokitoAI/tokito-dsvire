# Usage

This guide covers local extraction, the private HTTP service, optional visual
models, and the repository verification workflow.

## Local setup

Install Python 3.11+ and uv 0.12.3, then resolve the committed lock without
updating it:

```bash
uv sync --locked --extra test
uv run --frozen --no-sync pytest
```

`uv.lock` is the universal development graph. `requirements/runtime.lock` is
the hash-pinned container export. CI rejects drift between them.

When intentionally changing dependencies:

```bash
uv lock --upgrade-package <package>
uv export --locked --format requirements.txt --no-dev \
  --no-emit-project --no-header --output-file requirements/runtime.lock
uv run --frozen --no-sync python scripts/check_dependency_lock.py
```

Review the dependency, license, vulnerability, model, and container impact in
the same pull request. Never hand-edit either lock.

## Extract evidence

```bash
uv run --frozen --no-sync dsvire extract-evidence datasheet.pdf \
  --manufacturer "Texas Instruments" \
  --mpn TPS5430DDAR \
  --package SO-PowerPAD-8 \
  --out ./artifacts
```

The output is a versioned evidence pack. Each accepted region includes its page,
normalized bounding box, type, crop URI/hash, verification policy, and score
semantics. The extractor fails if the exact document identity cannot be
grounded.

## Run the service

Explicit loopback-only development mode:

```bash
DSVIRE_ENVIRONMENT=development DSVIRE_ALLOW_INSECURE_DEV=true \
  uv run uvicorn dsvire.api:app --host 127.0.0.1 --port 8081
```

Authenticated mode:

```bash
DSVIRE_ENVIRONMENT=production \
DSVIRE_SERVICE_TOKEN="replace-with-at-least-32-random-bytes" \
  uv run uvicorn dsvire.api:app --host 127.0.0.1 --port 8081
```

Example request:

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $DSVIRE_SERVICE_TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @datasheet.pdf \
  "http://127.0.0.1:8081/v1/evidence/symbol?manufacturer=Texas%20Instruments&mpn=TPS5430DDAR&package=SO-PowerPAD-8"
```

The private endpoint is intended for Tokito Cloud or another trusted service,
not direct desktop/browser exposure. Request size, page count, concurrency,
admission wait, wall time, CPU, memory, output, and scratch space are bounded.

## Query an immutable retrieval pack

The online cascade reads only content-addressed packs stored at
`$DSVIRE_DATA_DIR/retrieval-packs/<payload_sha256>.json`. The request repeats
the exact dense and multi-vector model identities; any missing, tampered,
symlinked, or model-incompatible pack fails closed. Query vectors must come
from those same pinned encoders—the service never substitutes a generic or
global-vector fallback.

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $DSVIRE_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @query.json \
  http://127.0.0.1:8081/v1/query
```

`query.json` contains `pack_sha256`, `models.dense`, `models.multi`, the
natural-language `query`, `dense_vector`, and token-level `multi_vectors`.
Optional `top_n`, `maxsim_k`, and `limit` values are bounded by the core. The
response binds every hit to pack/source/model/content hashes, page, normalized
box, region type, and the component scores. Query execution has separate
admission and timeout controls (`DSVIRE_MAX_CONCURRENT_QUERIES`,
`DSVIRE_QUERY_TIMEOUT_SECONDS`, and `DSVIRE_MAX_QUERY_BYTES`) and runs in a
killable resource-limited subprocess.

This endpoint exposes the implemented deterministic cascade. It does not make
the encoder calibrated, pass retrieval cycle v4, or authorize generated-symbol
publication.

## Optional ColSmol profile

Model files are hash-pinned and download-only:

```bash
uv sync --locked --extra colsmol
python scripts/acquire_model.py \
  --manifest evaluation/models/colsmol-256m.v1.json \
  --destination .cache/colsmol-offline
python scripts/evaluate_full_corpus_colsmol.py \
  --device cuda \
  --model-root .cache/colsmol-offline \
  --cache-root .cache/dsvire-eval \
  --offline \
  --json-out colsmol-development.json
```

The ColSmol and OpenCLIP extras are intentionally mutually exclusive because
their verified Torch stacks differ.

## Real-PDF regression gate

Official PDFs remain local and are verified against the registry hashes:

```bash
python scripts/evaluate_identity.py \
  --cache-dir .cache/dsvire-eval \
  --json-out identity-eval.json
```

Use `--offline` once the exact sources are present. Hash, identity, package, or
expected-negative drift fails closed.

## Documentation and release verification

```bash
python scripts/generate_docs_assets.py
git diff --exit-code -- examples docs/assets
python scripts/verify_release.py --json-out release-verification.json
```

The benchmark graphic is generated from committed result JSON. The workflow
raster is a reviewed composition of the actual TPS5430 page-3 regions and the
renderer output from the compiled Tokito symbol; it must not be replaced by a
synthetic datasheet drawing.

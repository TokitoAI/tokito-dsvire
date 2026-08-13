# Dependency locks

DS-ViRe uses one committed universal `uv.lock` for Python 3.11+ on supported
platforms. Runtime and compatible extras are resolved in one universal lock, so
an optional benchmark cannot silently select a different shared dependency.
The OpenCLIP and ColSmol extras are explicitly mutually exclusive because their
verified Torch lines differ; `uv` refuses an environment that requests both.

CI and release jobs install uv 0.12.3 through a commit-pinned setup action,
verify that `pyproject.toml` would not change the lock, and install with
`uv sync --locked`. Every command after installation uses
`uv run --frozen --no-sync`, which forbids resolution or environment mutation.

The service image has an additional, machine-consumable
`requirements/runtime.lock`. It is generated from the universal lock, contains
exact versions and artifact hashes, and is installed with pip
`--require-hashes`. The image starts from a digest-pinned Python manifest and
runs the source tree directly, so no build backend or dependency resolver runs
inside the image build.

## Intentional update procedure

Install uv 0.12.3, then run:

```bash
uv lock --upgrade
uv export --locked --format requirements.txt --no-dev --no-emit-project \
  --no-header --output-file requirements/runtime.lock
python scripts/check_dependency_lock.py
uv sync --locked --extra test --extra visual
uv run --frozen --no-sync python scripts/verify_release.py \
  --json-out release-verification.json
```

For an OpenCLIP dependency update, also install `--extra openclip` and run the
manual visual benchmark workflow. Review the complete lock diff, not only the
direct dependency line. A dependency PR must include any changed benchmark
evidence and must pass the container boundary tests.

For a ColSmol update, preserve exact pins for ColPali Engine, Transformers,
PEFT, Hugging Face Hub, Torch, and Torchvision, then regenerate its reviewable export:

```bash
uv export --locked --no-dev --extra colsmol --no-emit-project --no-hashes \
  --output-file requirements/colsmol.lock
uv sync --locked --extra test --extra colsmol
uv run --frozen --no-sync pip-audit --local --strict
```

`requirements/colsmol.lock` is audit evidence, not an image input and not a
substitute for `uv.lock`; model indexing is deliberately absent from the thin
production service image. Never resolve ColSmol and OpenCLIP together.

Every runtime lock change must also update
`policy/runtime-licenses.v1.json` with the exact normalized package/version and
license expression, then regenerate `THIRD_PARTY_NOTICES.md`:

```bash
uv run --frozen --no-sync python scripts/audit_runtime_licenses.py \
  --write-notices --json-out runtime-license-audit.json
```

CI fails for missing, stale, unknown, forbidden, version-mismatched, expired,
or absent required-license-file entries, and also fails if notices drift. A
`requires_legal_decision` entry must name an owner, evidence URL, concrete
obligations, and expiry; tagged releases refuse unresolved decisions. The
pinned pypdfium2 wheel is permissively licensed and the audit verifies that its
pypdfium2, PDFium, and native dependency license payloads are physically
present in the installed distribution. The technical policy is inventory and
enforcement evidence, not legal advice.

The base image digest is deliberately separate from the Python lock. Update the
tag and digest together after reviewing the upstream Python image, then let CI
build and smoke-test the exact manifest. Never replace the digest with a mutable
tag or reintroduce a packaging-tool upgrade inside the Dockerfile.

CI also builds the production Dockerfile twice with `--pull --no-cache`, exports
both container root filesystems, and compares a canonical inventory of every
path's type, mode, uid/gid, link target, size, and file SHA-256. Tar ordering and
mtimes are intentionally not identity; Docker's runtime-injected
`/etc/hostname`, `/etc/hosts`, and `/etc/resolv.conf` are the only excluded paths
and are named in the JSON evidence. A mismatch fails CI with up to 100 differing
paths. The uploaded `dsvire.image-reproducibility.v1` report binds the result to
the source commit, pinned base reference, both image IDs, entry counts, and both
normalized rootfs digests. This proves runtime-filesystem reproducibility on one
clean CI runner; it does not claim that provenance-bearing registry manifests or
Docker configuration timestamps are byte-identical.

The private-runner reproduction workflow also runs every Monday at 03:17 UTC
and remains manually dispatchable. Each run builds twice from `main` without
cache, fails on normalized-rootfs drift, retains the source/run-bound report and
full inventory for 90 days, and issues a GitHub artifact attestation over the
uploaded evidence digest. The workflow has read-only repository access plus
only the OIDC/attestation permissions needed to sign that evidence; it never
pushes or deploys an image. Cleanup remains unconditional.

The image installs Python packages with pip `--no-compile`. Prebuilt `.pyc`
files are deliberately absent because their headers incorporate install-time
source mtimes and caused 608 byte-level differences in the first cold-build
drill. This removes nondeterminism at its source rather than exempting bytecode
from comparison; Python may create runtime caches only where the non-root
process has a writable filesystem.

The final image layer also removes any nested app `__pycache__` directories and
normalizes `/app` directories to `0755` and files to `0644`. This is necessary
because source-checkout umasks differ across builders and CI may run Python
before building the image. The normalization applies to the copied read-only app
payload only; `/data/dsvire` is created and owned separately by the non-root
runtime user.

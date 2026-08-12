# Dependency locks

DS-ViRe uses one committed universal `uv.lock` for Python 3.11+ on supported
platforms. Runtime, test, visual, and OpenCLIP extras are resolved together, so
an optional benchmark cannot silently select a different shared dependency.

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

Every runtime lock change must also update
`policy/runtime-licenses.v1.json` with the exact normalized package/version and
license expression, then regenerate `THIRD_PARTY_NOTICES.md`:

```bash
uv run --frozen --no-sync python scripts/audit_runtime_licenses.py \
  --write-notices --json-out runtime-license-audit.json
```

CI fails for missing, stale, unknown, forbidden, version-mismatched, or expired
entries and also fails if the notices drift. A `requires_legal_decision` entry
must name an owner, evidence URL, concrete obligations, and expiry. It allows
review and CI only; tagged releases run `--require-release-ready` and refuse
all unresolved decisions. Today PyMuPDF 1.28.2 is such a decision because its
declared choice is AGPL-3.0-or-later or an Artifex commercial license. Before a
new production release, TokitoAI must record commercial coverage or obtain
counsel approval for the applicable AGPL source/network-use obligations. The
technical policy is inventory and enforcement evidence, not legal advice.

The base image digest is deliberately separate from the Python lock. Update the
tag and digest together after reviewing the upstream Python image, then let CI
build and smoke-test the exact manifest. Never replace the digest with a mutable
tag or reintroduce a packaging-tool upgrade inside the Dockerfile.

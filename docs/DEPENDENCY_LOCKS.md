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

The base image digest is deliberately separate from the Python lock. Update the
tag and digest together after reviewing the upstream Python image, then let CI
build and smoke-test the exact manifest. Never replace the digest with a mutable
tag or reintroduce a packaging-tool upgrade inside the Dockerfile.

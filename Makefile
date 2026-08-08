# DS-ViRe developer entry points.
#
# Everything here is a thin wrapper around scripts/ so contributors get a stable,
# one-line surface for the actions the repo runs today (fixture build + tests +
# demo runner). No environment magic: each target is exactly what it looks like.

PY := python3
PIP := $(PY) -m pip

FIXTURE_SLUG ?= tps5430ddar

.PHONY: help
help:
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: install-dev
install-dev:  ## Install Python dev deps for tests + fixture generation.
	$(PIP) install --user -r tests/requirements.txt

.PHONY: build-fixtures
build-fixtures:  ## Regenerate every evidence fixture (crops + hashes).
	$(PY) scripts/build_fixture.py

.PHONY: build-fixture
build-fixture:  ## Regenerate one fixture: `make build-fixture FIXTURE_SLUG=tps5430ddar`.
	$(PY) scripts/build_fixture.py $(FIXTURE_SLUG)

.PHONY: verify
verify:  ## Verify pipeline artifacts for one MPN slug against §7 criteria.
	$(PY) scripts/verify.py $(FIXTURE_SLUG)

.PHONY: demo
demo:  ## Run the full end-to-end pipeline for one MPN slug.
	$(PY) scripts/demo_run.py $(FIXTURE_SLUG)

.PHONY: test
test:  ## Run the full pytest suite.
	$(PY) -m pytest tests/ -q

.PHONY: test-verbose
test-verbose:  ## Run the full pytest suite with per-test output.
	$(PY) -m pytest tests/ -v

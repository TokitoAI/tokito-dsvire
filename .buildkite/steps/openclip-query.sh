#!/usr/bin/env bash
# OpenCLIP query-to-crop retrieval benchmark, ranking query text against
# every registered crop in the development split.
#
# Ported from .github/workflows/openclip-query-benchmark.yml. That workflow
# stayed on the self-hosted `tokito-vps` GitHub Actions runner, unlike
# everything else in this repository, for two reasons this script makes
# concrete: the warm corpus cache and the pinned OpenCLIP weights, both of
# which existed only on that machine. The runner is being decommissioned;
# both assets have been restored onto the Buildkite build host instead (see
# common.sh), so this runs directly on that host, on the `linux` queue of the
# `build` cluster — a faithful port, not a container wrapper, because the
# GitHub Actions job never ran in a container either.
set -euo pipefail
# shellcheck source=.buildkite/steps/common.sh
source "$(dirname "$0")/common.sh"

require_uv_version
require_benchmark_corpus

MODEL_SHA256=ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6
MODEL_WEIGHTS="$TOKITO_BENCHMARK_ASSETS/.dsvire-benchmark-models/${MODEL_SHA256}.safetensors"
require_benchmark_model "$MODEL_WEIGHTS"

cd "$BUILDKITE_BUILD_CHECKOUT_PATH"

echo "--- :mag: checking dependency lock"
# No setup-python equivalent: uv provisions the 3.12 interpreter itself.
# --no-project skips syncing the project environment — this script only
# shells out to `uv` and touches stdlib, so there is nothing to sync yet.
uv run --no-project python scripts/check_dependency_lock.py

echo "--- :snake: installing frozen visual runtime"
uv sync --locked --extra test --extra visual --extra openclip

echo "--- :closed_lock_with_key: auditing resolved locked visual runtime"
# tokito-dsvire itself is uninstalled first so pip-audit's dependency walk
# cannot report a vulnerability in the package we ship as if it were a
# third-party risk, then re-synced immediately after so the run step below
# has the full environment back.
uv pip uninstall tokito-dsvire
uv run --frozen --no-sync pip-audit --local --strict
uv sync --locked --extra test --extra visual --extra openclip

echo "--- :bar_chart: ranking query text against every registered crop"
RESULT_DIR="$BUILDKITE_BUILD_CHECKOUT_PATH/ci-out"
mkdir -p "$RESULT_DIR"
result="$RESULT_DIR/openclip-query-development-${BUILDKITE_COMMIT}.json"
uv run --frozen --no-sync python scripts/evaluate_full_corpus_openclip_baseline.py \
  --cache-root "$BENCHMARK_CORPUS" \
  --download-cache "$BENCHMARK_SCRATCH/dsvire-openclip-query-sources" \
  --model "$MODEL_WEIGHTS" \
  --json-out "$result"
(cd "$RESULT_DIR" && sha256sum "$(basename "$result")" > "$(basename "$result").sha256")

# actions/upload-artifact's `if-no-files-found: error` has no Buildkite
# equivalent, so check explicitly rather than let a silent no-op pass for
# success.
[ -f "$result" ] || { echo "no benchmark evidence produced at $result" >&2; exit 1; }
[ -f "${result}.sha256" ] || { echo "no sha256 sidecar produced at ${result}.sha256" >&2; exit 1; }

echo "--- :package: publishing compact benchmark evidence only"
# Same intent as the workflow's "Publish compact benchmark evidence only"
# step: just the JSON and its sidecar, nothing else artifacts/ produced
# (there is no artifacts/ dir here at all — everything lands in ci-out/).
buildkite-agent artifact upload "ci-out/$(basename "$result")"
buildkite-agent artifact upload "ci-out/$(basename "$result").sha256"

#!/usr/bin/env bash
# Bootstrap step: hand the real benchmark pipeline to Buildkite.
#
# A committed script rather than an inline `buildkite-agent pipeline upload`,
# because the agents run with no-command-eval=true and refuse anything that
# is not a path in the checkout.
#
# Buildkite has no workflow_dispatch. The equivalent gesture is starting a
# build with an environment variable set — TASK, validated below — which is
# why this fails loudly on a missing or unknown TASK instead of uploading a
# pipeline whose steps are all `if:`-gated off. That produces a build that
# does nothing and still reports success, which is the exact failure mode
# this guards against (same pattern as .buildkite/staging/upload.sh in
# tokito-api, just against a much smaller blast radius here: an on-demand
# benchmark, not a staging deploy).
set -euo pipefail

case "${TASK:-}" in
  openclip-query)
    buildkite-agent pipeline upload .buildkite/benchmark-openclip-query.yml
    ;;
  query-ranking)
    buildkite-agent pipeline upload .buildkite/benchmark-query-ranking.yml
    ;;
  "")
    echo "TASK is not set. Start this build with, for example:" >&2
    echo "  TASK=openclip-query" >&2
    echo "  TASK=query-ranking" >&2
    exit 1
    ;;
  *)
    echo "TASK='${TASK}' is not one of: openclip-query, query-ranking" >&2
    exit 1
    ;;
esac

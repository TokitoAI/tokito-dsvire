from __future__ import annotations

import json
import tomllib
from pathlib import Path

from dsvire.visual_adapters import (
    OPENCLIP_MODEL_BYTES,
    OPENCLIP_MODEL_REVISION,
    OPENCLIP_MODEL_SHA256,
    OPENCLIP_MODEL_URL,
)


def test_visual_runtime_is_optional_but_ci_and_release_verify_it() -> None:
    root = Path(__file__).parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    visual = pyproject["project"]["optional-dependencies"]["visual"]

    assert visual == [
        "numpy>=2.0,<2.5",
        "onnxruntime>=1.27,<2",
        "psutil>=7.2.2,<8",
        "rapidocr>=3.9.2,<4",
    ]
    for workflow_name in ["ci.yml", "release.yml"]:
        workflow = (root / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
        assert "uv sync --locked --extra test --extra visual" in workflow
        assert "python scripts/verify_release.py" in workflow
        assert "uv run --frozen --no-sync" in workflow


def test_full_visual_benchmark_workflow_is_manual_pinned_and_evidence_only() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/visual-benchmark.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 20" in workflow
    assert "- text-layout" in workflow
    assert "- rapidocr" in workflow
    assert "- openclip" in workflow
    assert 'if [ "$ADAPTER" = openclip ]' in workflow
    assert "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd" in workflow
    assert "actions/setup-python@e797f83bcb11b83ae66e0230d6156d7c80228e7c" in workflow
    assert "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78" in workflow
    assert "uv sync --locked" in workflow
    assert "--extra openclip" in workflow
    upload_artifact = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload_artifact in workflow
    assert upload_artifact in (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert '"$RUNNER_TEMP/dsvire-visual-sources"' in workflow
    assert "sha256sum" in workflow
    assert 'cd "$RESULT_DIR"' in workflow
    assert "artifacts/*.json" in workflow
    assert "artifacts/*.json.sha256" in workflow
    assert "retention-days: 30" in workflow


def test_full_corpus_query_workflow_is_manual_pinned_and_source_free() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/query-ranking-benchmark.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert "runs-on: [self-hosted, Linux, X64, tokito-vps, private-build]" in workflow
    assert "--cache-root /opt/actions-runner/.dsvire-benchmark-sources" in workflow
    assert '--download-cache "$RUNNER_TEMP/dsvire-query-sources"' in workflow
    assert "--ranking-out" not in workflow
    assert "artifacts/*.json" in workflow
    assert "retention-days: 30" in workflow
    assert "artifacts/*.pdf" not in workflow
    assert "actions/cache" not in workflow


def test_openclip_query_workflow_is_private_pinned_and_source_free() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/openclip-query-benchmark.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert "runs-on: [self-hosted, Linux, X64, tokito-vps, private-build]" in workflow
    assert "--extra openclip" in workflow
    assert "ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6" in workflow
    assert "--ranking-out" not in workflow
    assert "artifacts/*.json" in workflow
    assert "retention-days: 30" in workflow
    assert "artifacts/*.pdf" not in workflow
    assert "artifacts/*.safetensors" not in workflow
    assert "*.pdf" not in workflow


def test_openclip_model_registry_matches_the_fail_closed_runtime_contract() -> None:
    root = Path(__file__).parents[1]
    registry = json.loads((root / "evaluation/visual_models.v1.json").read_text(encoding="utf-8"))

    assert registry["schema_version"] == "dsvire.visual-model-registry.v1"
    assert len(registry["models"]) == 1
    model = registry["models"][0]
    assert set(model) == {
        "id",
        "architecture",
        "implementation",
        "source_url",
        "source_revision",
        "content_sha256",
        "content_bytes",
        "license",
        "redistribution",
        "terms_note",
    }
    assert model["source_url"] == OPENCLIP_MODEL_URL
    assert model["source_revision"] == OPENCLIP_MODEL_REVISION
    assert model["content_sha256"] == OPENCLIP_MODEL_SHA256
    assert model["content_bytes"] == OPENCLIP_MODEL_BYTES
    assert model["redistribution"] == "download_only"

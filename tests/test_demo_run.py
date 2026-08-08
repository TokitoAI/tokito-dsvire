"""Unit tests for scripts/demo_run.py.

Tests the orchestrator's non-network surface: config loading, missing-tool
handling, missing-fixture handling. Full subprocess-based stage execution
is exercised by the integration path when teammates' CLIs are on PATH; here
we verify the runner fails loudly and cleanly instead of silently.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import demo_run  # noqa: E402


def test_config_from_env_defaults() -> None:
    cfg = demo_run.Config.from_env({})
    assert cfg.extract_cmd == "tokito-symbol-extractor"
    assert cfg.compile_cmd == "tokito-symbol-compile"
    assert cfg.tokito_ai_url == "http://localhost:8080"
    assert cfg.tokito_ai_token is None
    assert cfg.mcp_pack_cmd == "tokito-mcp-pack"
    assert cfg.mcp_url == "http://localhost:8090/mcp"


def test_config_from_env_overrides() -> None:
    cfg = demo_run.Config.from_env({
        "TOKITO_EXTRACT_CMD": "cargo run --manifest-path ../tokito-ai/Cargo.toml --bin sx --",
        "TOKITO_AI_URL": "https://api.tokito.dev",
        "TOKITO_AI_TOKEN": "jwt-xxx",
        "TOKITO_MCP_URL": "https://mcp.tokito.dev/mcp",
    })
    assert cfg.extract_cmd.startswith("cargo run")
    assert cfg.tokito_ai_url == "https://api.tokito.dev"
    assert cfg.tokito_ai_token == "jwt-xxx"
    assert cfg.mcp_url == "https://mcp.tokito.dev/mcp"


def test_require_tool_missing_raises() -> None:
    with pytest.raises(demo_run.StageError) as ei:
        demo_run._require_tool("this-binary-does-not-exist-anywhere-42")
    assert "not found on PATH" in str(ei.value)


def test_require_tool_empty_raises() -> None:
    with pytest.raises(demo_run.StageError):
        demo_run._require_tool("")


def test_require_tool_resolves_present_binary() -> None:
    demo_run._require_tool("python3")  # must not raise


def test_run_missing_fixture_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = demo_run.run(
        slug="does-not-exist",
        cfg=demo_run.Config.from_env({}),
        artifacts_root=tmp_path,
        stages=("extract",),
    )
    assert rc == 2
    assert "fixture 'does-not-exist' not found" in capsys.readouterr().err


def test_run_verify_only_on_bundle_only_reports_missing_stages(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """With only the fixture bundle present, the verify stage must report
    downstream artifacts as MISSING and exit non-zero — never PASS by default."""
    rc = demo_run.run(
        slug="tps5430ddar",  # real committed fixture
        cfg=demo_run.Config.from_env({}),
        artifacts_root=tmp_path,
        stages=("verify",),
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert "spec.file_exists" in out
    assert "FAIL" in out

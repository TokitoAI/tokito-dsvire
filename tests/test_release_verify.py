from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dsvire.release_verify import ReleaseVerificationError, verify_release, write_report


def _completed(
    command: object, returncode: int = 0, stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def test_release_verifier_runs_every_gate_in_order() -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command == ("uv", "--version"):
            return _completed(command, stdout="uv 0.12.3\n")
        if "scripts/evaluate_robustness.py" in command:
            output = Path(command[command.index("--json-out") + 1])
            output.write_text(
                json.dumps(
                    {
                        "schema_version": "dsvire.robustness-result.v1",
                        "ok": True,
                        "case_count": 11,
                        "manifest_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
        return _completed(command)

    report = verify_release(runner=runner)

    assert report["ok"] is True
    assert [stage["name"] for stage in report["stages"]] == [
        "dependency-lock",
        "static-types",
        "lint",
        "format",
        "compile",
        "tests-and-artifacts",
        "generated-robustness-corpus",
        "package-build",
        "runtime-vulnerability-audit",
    ]
    assert any(command[:2] == ("pytest", "-q") for command in commands)
    assert any("scripts/evaluate_robustness.py" in command for command in commands)
    assert any("--require-hashes" in command for command in commands)
    assert report["artifacts"]["robustness"]["case_count"] == 11


def test_release_verifier_propagates_the_first_failure() -> None:
    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command == ("uv", "--version"):
            return _completed(command, stdout="uv 0.12.3\n")
        return _completed(command, returncode=9)

    with pytest.raises(ReleaseVerificationError, match=r"dependency-lock.*exit code 9"):
        verify_release(runner=runner)


def test_release_verifier_rejects_tool_version_drift() -> None:
    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(command, stdout="uv 99.0.0\n")

    with pytest.raises(ReleaseVerificationError, match="uv version gate failed"):
        verify_release(runner=runner)


def test_release_report_is_atomic_json(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    write_report({"ok": True}, output)
    assert output.read_text(encoding="utf-8") == '{\n  "ok": true\n}\n'
    assert not output.with_suffix(".json.tmp").exists()

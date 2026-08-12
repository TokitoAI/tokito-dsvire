"""One fail-closed, reviewable release verification pipeline."""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UV_VERSION = "0.12.3"


class ReleaseVerificationError(RuntimeError):
    """A required release gate failed."""


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class StageResult:
    name: str
    elapsed_seconds: float


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _stages(build_out: Path, robustness_out: Path) -> tuple[Stage, ...]:
    python = sys.executable
    return (
        Stage("dependency-lock", (python, "scripts/check_dependency_lock.py")),
        Stage("static-types", ("mypy", "src/dsvire", "scripts")),
        Stage("lint", ("ruff", "check", ".")),
        Stage("format", ("ruff", "format", "--check", ".")),
        Stage("compile", (python, "-m", "compileall", "-q", "src", "scripts")),
        Stage("tests-and-artifacts", ("pytest", "-q")),
        Stage(
            "generated-robustness-corpus",
            (
                python,
                "scripts/evaluate_robustness.py",
                "--json-out",
                str(robustness_out),
            ),
        ),
        Stage(
            "package-build",
            (python, "-m", "build", "--no-isolation", "--outdir", str(build_out)),
        ),
        Stage(
            "runtime-vulnerability-audit",
            (
                "pip-audit",
                "--requirement",
                "requirements/runtime.lock",
                "--strict",
                "--require-hashes",
            ),
        ),
    )


def verify_release(*, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Run every offline-safe release gate in order and return bounded evidence."""
    version = runner(
        ("uv", "--version"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    expected = f"uv {EXPECTED_UV_VERSION}"
    actual_version = version.stdout.strip()
    if (
        version.returncode != 0
        or re.match(rf"^{re.escape(expected)}(?:\s|$)", actual_version) is None
    ):
        raise ReleaseVerificationError(
            f"uv version gate failed: expected {expected!r}, got {actual_version!r}"
        )

    results: list[StageResult] = []
    with tempfile.TemporaryDirectory(prefix="dsvire-release-") as directory:
        build_out = Path(directory) / "dist"
        robustness_out = Path(directory) / "robustness.json"
        for stage in _stages(build_out, robustness_out):
            started = time.perf_counter()
            completed = runner(
                stage.command,
                cwd=ROOT,
                check=False,
                text=True,
            )
            elapsed = time.perf_counter() - started
            if completed.returncode != 0:
                raise ReleaseVerificationError(
                    f"release stage {stage.name!r} failed with exit code {completed.returncode}"
                )
            results.append(StageResult(stage.name, elapsed))
        try:
            robustness = json.loads(robustness_out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseVerificationError(
                "generated robustness corpus did not emit valid evidence"
            ) from exc
        if (
            robustness.get("schema_version") != "dsvire.robustness-result.v1"
            or robustness.get("ok") is not True
            or not isinstance(robustness.get("case_count"), int)
            or robustness["case_count"] < 1
            or not re.fullmatch(r"[0-9a-f]{64}", str(robustness.get("manifest_sha256", "")))
        ):
            raise ReleaseVerificationError("generated robustness evidence failed validation")
    return {
        "schema_version": "dsvire.release-verification.v1",
        "ok": True,
        "uv_version": EXPECTED_UV_VERSION,
        "stages": [dataclasses.asdict(result) for result in results],
        "artifacts": {
            "robustness": {
                "schema_version": robustness["schema_version"],
                "manifest_sha256": robustness["manifest_sha256"],
                "case_count": robustness["case_count"],
            }
        },
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)

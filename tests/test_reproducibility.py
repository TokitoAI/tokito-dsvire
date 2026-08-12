from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SETUP_UV = "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78"


def test_universal_lock_covers_every_supported_environment() -> None:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.11"' in lock
    for package in [
        "tokito-dsvire",
        "pypdf",
        "pytest",
        "hatchling",
        "rapidocr",
        "onnxruntime",
        "open-clip-torch",
        "torch",
        "torchvision",
    ]:
        assert f'name = "{package}"' in lock

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'python_version = "3.11"' in pyproject
    assert '"numpy>=2.0,<2.5"' in pyproject


def test_container_runtime_export_is_exact_and_hash_pinned() -> None:
    runtime_lock = (ROOT / "requirements/runtime.lock").read_text(encoding="utf-8")
    requirements = [
        line for line in runtime_lock.splitlines() if line and not line.startswith((" ", "#"))
    ]

    assert requirements
    assert all("==" in requirement for requirement in requirements)
    assert runtime_lock.count("--hash=sha256:") >= len(requirements)
    assert not re.search(r"(?<![=])>=(?!=)", runtime_lock)


def test_container_never_resolves_dependencies_or_build_requirements() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"^FROM python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}$", dockerfile, re.M)
    assert "--require-hashes -r requirements/runtime.lock" in dockerfile
    assert "PYTHONPATH=/app/src" in dockerfile
    assert "COPY fixtures/robustness ./fixtures/robustness" in dockerfile
    assert "COPY scripts/evaluate_robustness.py ./scripts/evaluate_robustness.py" in dockerfile
    assert "COPY THIRD_PARTY_NOTICES.md ./THIRD_PARTY_NOTICES.md" in dockerfile
    assert "COPY policy ./policy" in dockerfile
    assert "pip install --no-cache-dir ." not in dockerfile
    assert "pip install --no-cache-dir --upgrade" not in dockerfile


def test_every_python_workflow_enforces_the_same_frozen_lock() -> None:
    for name in ["ci.yml", "release.yml", "visual-benchmark.yml"]:
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert SETUP_UV in workflow
        assert "version: '0.12.3'" in workflow
        assert "uv sync --locked" in workflow
        assert "uv run --frozen --no-sync" in workflow
        assert "pip install -e" not in workflow
        if name == "visual-benchmark.yml":
            assert "python scripts/check_dependency_lock.py" in workflow
        else:
            assert "python scripts/verify_release.py" in workflow
            assert "Container robustness corpus" in workflow
            assert "scripts/evaluate_robustness.py" in workflow
            assert "Container runtime license audit" in workflow
            assert "scripts/audit_runtime_licenses.py" in workflow
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert release.count("--require-release-ready") == 2

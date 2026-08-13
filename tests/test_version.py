from __future__ import annotations

import tomllib
from pathlib import Path

import dsvire


def test_runtime_and_package_versions_match() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert dsvire.__version__ == pyproject["project"]["version"]
    assert dsvire.__version__ == "0.5.0"

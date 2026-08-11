from __future__ import annotations

import tomllib
from pathlib import Path


def test_visual_runtime_is_optional_but_ci_and_release_verify_it() -> None:
    root = Path(__file__).parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    visual = pyproject["project"]["optional-dependencies"]["visual"]

    assert visual == [
        "onnxruntime>=1.27,<2",
        "psutil>=7.2.2,<8",
        "rapidocr>=3.9.2,<4",
    ]
    for workflow_name in ["ci.yml", "release.yml"]:
        workflow = (root / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
        assert ".[test,visual]" in workflow
        assert "pip_audit --local --strict" in workflow
        assert "pip install -e . --no-deps" in workflow

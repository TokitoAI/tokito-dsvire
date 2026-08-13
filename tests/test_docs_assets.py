from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_public_examples_regenerate_byte_identically(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    subprocess.run(
        [sys.executable, "scripts/generate_docs_assets.py", "--output-root", str(tmp_path)],
        cwd=root,
        check=True,
    )

    generated = ("docs/assets/product-workflow.svg", "docs/assets/benchmark-overview.svg")
    for relative in generated:
        assert (tmp_path / relative).read_bytes() == (root / relative).read_bytes()


def test_public_workflow_is_source_free_and_names_real_fixture_output() -> None:
    root = Path(__file__).parents[1]
    text = (root / "docs/assets/product-workflow.svg").read_text(encoding="utf-8")

    assert "TPS5430DDAR" in text
    assert "BOOT" in text and "VSENSE" in text and "VIN" in text
    assert "Texas Instruments" not in text

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

    generated = ("docs/assets/benchmark-overview.svg",)
    for relative in generated:
        assert (tmp_path / relative).read_bytes() == (root / relative).read_bytes()


def test_public_workflow_is_a_real_raster_composition() -> None:
    root = Path(__file__).parents[1]
    from PIL import Image

    path = root / "docs/assets/product-workflow.png"
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 900)
        assert image.mode == "RGB"

    assert not (root / "docs/assets/product-workflow.svg").exists()

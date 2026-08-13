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

    generated = (
        "examples/tps5430ddar-evidence-summary.json",
        "docs/assets/evidence-bundle-example.svg",
        "docs/assets/multivendor-development-benchmark.svg",
        "docs/assets/service-load-evidence.svg",
        "docs/assets/staging-restart-load.svg",
        "docs/assets/staging-soak.svg",
        "docs/assets/staging-recovery.svg",
        "docs/assets/staging-schema-recovery.svg",
        "examples/corpus-coverage.json",
        "docs/assets/corpus-coverage.svg",
        "docs/assets/query-ranking-canary.svg",
        "docs/assets/full-corpus-text-development.svg",
        "docs/assets/full-corpus-retrieval-comparison.svg",
        "docs/assets/full-corpus-colsmol-development.svg",
    )
    for relative in generated:
        assert (tmp_path / relative).read_bytes() == (root / relative).read_bytes()


def test_public_example_fails_closed_and_names_score_semantics() -> None:
    root = Path(__file__).parents[1]
    text = (root / "examples/tps5430ddar-evidence-summary.json").read_text(encoding="utf-8")

    assert '"publication_eligible": false' in text
    assert '"score_semantics": "heuristic_evidence_strength"' in text
    assert "calibrated_probability" in text

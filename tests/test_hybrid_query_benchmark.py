from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parents[1]
COMMITTED = ROOT / "evaluation/results/hybrid-query-core-capacity-2026-08-13.json"


def test_hybrid_query_benchmark_is_schema_valid_and_semantically_repeatable(tmp_path: Path) -> None:
    outputs = [tmp_path / "a.json", tmp_path / "b.json"]
    for output in outputs:
        subprocess.run(
            [
                sys.executable,
                "scripts/benchmark_hybrid_query_core.py",
                "--dimension",
                "4",
                "--patches",
                "2",
                "--top-n",
                "8",
                "--maxsim-k",
                "4",
                "--json-out",
                str(output),
            ],
            cwd=ROOT,
            check=True,
        )
    first, second = (json.loads(path.read_text()) for path in outputs)
    schema = json.loads(
        (ROOT / "scripts/schema/hybrid_query_core_benchmark_v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(first, schema)
    assert first["result_sha256"] == second["result_sha256"]
    assert first["order_sha256"] == second["order_sha256"]
    assert first["scope"]["regions"] == 209
    assert first["scope"]["queries"] == 90
    assert first["scope"]["maxsim_k"] == 4


def test_committed_capacity_evidence_matches_docs_and_schema() -> None:
    result = json.loads(COMMITTED.read_text())
    schema = json.loads(
        (ROOT / "scripts/schema/hybrid_query_core_benchmark_v1.schema.json").read_text()
    )
    jsonschema.validate(result, schema)
    examples = (ROOT / "docs/EXAMPLES.md").read_text()
    readme = (ROOT / "README.md").read_text()
    svg = (ROOT / "docs/assets/hybrid-query-core-capacity.svg").read_text()
    assert f"{result['query']['p95_ms']:.2f} ms" in examples
    assert f"{result['query']['p95_ms']:.2f} ms" in readme
    assert f"{result['query']['p95_ms']:.2f} ms" in svg
    assert result["result_sha256"][:8] in examples
    assert result["result_sha256"][-5:] in examples
    assert result["order_sha256"][:8] in svg
    assert result["order_sha256"][-5:] in svg

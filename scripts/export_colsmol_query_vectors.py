"""Export private, digest-bound ColSmol query vectors without indexing documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.colsmol_encoder import ColSmolEncoder
from dsvire.colsmol_reproduction import build_query_vector_artifact
from dsvire.corpus_coverage import load_query_registry
from dsvire.model_manifest import load_model_manifest
from dsvire.visual_registry import load_visual_registry_data

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "evaluation/visual_registry.v1.json"
    )
    parser.add_argument("--queries", type=Path, default=ROOT / "evaluation/query_registry.v2.json")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "evaluation/models/colsmol-256m.v1.json"
    )
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    visual = load_visual_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
    queries = load_query_registry(json.loads(args.queries.read_text(encoding="utf-8")), visual)
    manifest = load_model_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    encoder = ColSmolEncoder(manifest, args.model_root, device=args.device)
    records = []
    for query in sorted(
        (item for item in queries.queries if item.split == "development"),
        key=lambda item: item.query_id,
    ):
        vectors = encoder.encode_queries([query.query_text])[0]
        records.append(
            {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "vectors": [list(row) for row in vectors],
            }
        )
    artifact = build_query_vector_artifact(
        query_registry_sha256=queries.content_sha256,
        visual_registry_sha256=visual.content_sha256,
        model_id=encoder.model_id,
        model_sha256=encoder.model_sha256,
        dimension=encoder.dimension,
        queries=records,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

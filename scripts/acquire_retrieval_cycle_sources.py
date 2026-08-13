from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.retrieval_source_seal import acquire_source_manifest, write_manifest_atomic

ROOT = Path(__file__).parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal official sources for retrieval cycle v2")
    parser.add_argument(
        "--plan", type=Path, default=ROOT / "evaluation/retrieval_cycle_v2_preregistration.json"
    )
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "evaluation/visual_registry.v1.json").read_text(encoding="utf-8"))
    consumed = {item["id"] for item in registry["documents"]} | {
        item["document_group"] for item in registry["documents"]
    }
    manifest = acquire_source_manifest(plan, cache_dir=args.cache, consumed_family_ids=consumed)
    write_manifest_atomic(manifest, args.out)
    print(
        json.dumps(
            {
                "complete": manifest["complete"],
                "sources": len(manifest["sources"]),
                "invalidations": len(manifest["invalidations"]),
                "manifest_sha256": manifest["manifest_sha256"],
            }
        )
    )
    return 0 if manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

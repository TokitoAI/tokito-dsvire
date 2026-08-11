"""Run the hash-pinned real-PDF identity evaluation registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.eval_download import fetch_hash_pinned_pdf
from dsvire.evaluation import DocumentCase, evaluate_registry, load_registry_data

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "evaluation" / "identity_registry.v1.json"


def _download(case: DocumentCase, cache_dir: Path, *, offline: bool) -> bytes:
    return fetch_hash_pinned_pdf(
        case_id=case.case_id,
        source_url=case.source_url,
        content_sha256=case.content_sha256,
        cache_dir=cache_dir,
        offline=offline,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    try:
        registry = load_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
        result = evaluate_registry(
            registry,
            lambda case: _download(case, args.cache_dir, offline=args.offline),
            output_root=args.output_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out is not None:
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

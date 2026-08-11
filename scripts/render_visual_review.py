"""Download hash-pinned registry PDFs and render local human-review sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.eval_download import fetch_hash_pinned_pdf
from dsvire.visual_registry import load_visual_registry_data
from dsvire.visual_review import write_review_sheet

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "evaluation" / "visual_registry.v1.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        registry = load_visual_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
        for document in registry.documents:
            payload = fetch_hash_pinned_pdf(
                case_id=document.document_id,
                source_url=document.source.url,
                content_sha256=document.content_sha256,
                cache_dir=args.cache_dir,
                offline=args.offline,
            )
            print(write_review_sheet(payload, document, args.out_dir))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

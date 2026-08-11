"""Benchmark one adapter on the hash-pinned visual annotation registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.eval_download import fetch_hash_pinned_file, fetch_hash_pinned_pdf
from dsvire.visual_adapters import (
    OPENCLIP_MODEL_BYTES,
    OPENCLIP_MODEL_SHA256,
    OPENCLIP_MODEL_URL,
    OpenClipAdapter,
    RapidOcrAdapter,
    TextLayoutAdapter,
)
from dsvire.visual_benchmark import benchmark_registry
from dsvire.visual_registry import load_visual_registry_data

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "evaluation" / "visual_registry.v1.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--adapter", choices=["text-layout", "rapidocr", "openclip"], required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        registry = load_visual_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
        if args.adapter == "text-layout":
            adapter = TextLayoutAdapter()
        elif args.adapter == "rapidocr":
            adapter = RapidOcrAdapter()
        else:
            model_path = fetch_hash_pinned_file(
                artifact_id="openclip-vit-b-32-laion2b-s34b-b79k",
                source_url=OPENCLIP_MODEL_URL,
                content_sha256=OPENCLIP_MODEL_SHA256,
                expected_bytes=OPENCLIP_MODEL_BYTES,
                max_bytes=OPENCLIP_MODEL_BYTES,
                cache_dir=args.cache_dir / "models",
                suffix=".safetensors",
                offline=args.offline,
            )
            adapter = OpenClipAdapter(model_path)
        result = benchmark_registry(
            registry,
            lambda document: fetch_hash_pinned_pdf(
                case_id=document.document_id,
                source_url=document.source.url,
                content_sha256=document.content_sha256,
                cache_dir=args.cache_dir,
                offline=args.offline,
            ),
            adapter,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out is not None:
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    # Development/unreviewed scores are useful comparison evidence but cannot
    # pass a publication/calibration gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

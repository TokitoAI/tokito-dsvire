"""Run the sealed cycle v5 eval path: calibrate, then evaluate once.

Live late-interaction encoder is pinned ColQwen2-2B. Frozen cycle v5 still
names ColSmol; ColQwen scores are a comparator on the same sealed queries.
device_map=auto is inference placement, not the 20 GB training profile.
Text-layout visual scores keep similarity semantics and are not claimed as
EGVV calibrated probabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from dsvire.cycle_execution import assert_score_access_authorized, inspect_cycle_v5
from dsvire.cycle_source_cache import family_ids_from_plan, materialize_sealed_cycle_pdfs

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".cache" / "cycle-v5-work"
COLQWEN_MANIFEST = ROOT / "evaluation/models/colqwen2-v1.0-hf.json"
COLQWEN_OFFLINE = ROOT / ".cache" / "colqwen2-offline"
SOURCE_MANIFEST = ROOT / "evaluation/retrieval_cycle_v5_source_manifest.json"
PLAN = ROOT / "evaluation/retrieval_cycle_v5_preregistration.json"


def _run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=ROOT)


def _run_colqwen(
    python: str,
    *,
    registry: Path,
    queries: Path,
    model_root: Path,
    cache_root: Path,
    device: str,
    results: Path,
) -> None:
    for split in ("calibration", "evaluation"):
        _run(
            [
                python,
                "scripts/evaluate_full_corpus_colqwen.py",
                "--registry",
                str(registry),
                "--queries",
                str(queries),
                "--model-root",
                str(model_root),
                "--cache-root",
                str(cache_root),
                "--offline",
                "--device",
                device,
                "--split",
                split,
                "--json-out",
                str(results / f"cycle-v5-colqwen-{split}.json"),
                "--ranking-out",
                str(results / f"cycle-v5-colqwen-{split}-rankings.json"),
            ]
        )


def _detected_vram_mb() -> int | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None
    completed = subprocess.run(
        [
            nvidia_smi,
            "--query-gpu=memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    line = completed.stdout.strip().splitlines()[0].strip()
    return int(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--skip-colqwen", action="store_true")
    parser.add_argument("--colqwen-model-root", type=Path)
    parser.add_argument(
        "--colqwen-device",
        choices=("cpu", "cuda", "auto"),
        default="auto",
        help="auto places weights on GPU first and spills the rest to CPU RAM",
    )
    parser.add_argument("--also-colsmol", action="store_true")
    parser.add_argument("--skip-colsmol", action="store_true")
    parser.add_argument("--colsmol-model-root", type=Path)
    parser.add_argument(
        "--colsmol-device",
        choices=("cpu", "cuda", "auto"),
        default="auto",
        help="kept for the historical ColSmol comparator",
    )
    parser.add_argument(
        "--no-acquire-model",
        action="store_true",
        help="fail closed if ColQwen2 is not already materialized",
    )
    args = parser.parse_args()
    status = inspect_cycle_v5()
    assert_score_access_authorized(status)
    work = args.work
    results = work / "eval"
    results.mkdir(parents=True, exist_ok=True)
    pdf_cache = work / "eval-pdf-cache"
    pdf_cache.mkdir(parents=True, exist_ok=True)
    cache_root = work / "sources"
    cache_root.mkdir(parents=True, exist_ok=True)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    materialize_sealed_cycle_pdfs(
        source_manifest,
        cache_root,
        expected_family_ids=family_ids_from_plan(plan),
        offline=False,
    )
    for path in cache_root.rglob("*.pdf"):
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        destination = pdf_cache / f"{digest}.pdf"
        if not destination.exists():
            destination.write_bytes(path.read_bytes())
    python = sys.executable
    _run(
        [
            python,
            "scripts/export_cycle_v5_eval_artifacts.py",
            "--visual-out",
            str(results / "visual_registry.json"),
            "--queries-out",
            str(results / "query_registry.json"),
            "--split-plan-out",
            str(results / "visual_split_plan.json"),
        ]
    )
    registry = results / "visual_registry.json"
    queries = results / "query_registry.json"
    split_plan = results / "visual_split_plan.json"
    for split in ("calibration", "evaluation"):
        _run(
            [
                python,
                "scripts/evaluate_full_corpus_text_baseline.py",
                "--registry",
                str(registry),
                "--queries",
                str(queries),
                "--cache-root",
                str(cache_root),
                "--offline",
                "--split",
                split,
                "--json-out",
                str(results / f"cycle-v5-text-{split}.json"),
                "--ranking-out",
                str(results / f"cycle-v5-text-{split}-rankings.json"),
            ]
        )
        _run(
            [
                python,
                "scripts/evaluate_visual.py",
                "--registry",
                str(registry),
                "--split-plan",
                str(split_plan),
                "--cache-dir",
                str(pdf_cache),
                "--adapter",
                "text-layout",
                "--split",
                split,
                "--offline",
                "--json-out",
                str(results / f"cycle-v5-visual-text-layout-{split}.json"),
            ]
        )
    _run(
        [
            python,
            "scripts/evaluate_visual_policy.py",
            "freeze",
            "--calibration-benchmark",
            str(results / "cycle-v5-visual-text-layout-calibration.json"),
            "--json-out",
            str(results / "cycle-v5-visual-text-layout-policy.json"),
        ]
    )
    _run(
        [
            python,
            "scripts/evaluate_visual_policy.py",
            "evaluate",
            "--evaluation-benchmark",
            str(results / "cycle-v5-visual-text-layout-evaluation.json"),
            "--policy",
            str(results / "cycle-v5-visual-text-layout-policy.json"),
            "--json-out",
            str(results / "cycle-v5-visual-text-layout-evaluation-once.json"),
        ]
    )
    vram = _detected_vram_mb()
    colqwen_root = args.colqwen_model_root
    if colqwen_root is None:
        colqwen_root = COLQWEN_OFFLINE
    weights = colqwen_root / "weights" / "model.safetensors"
    if args.skip_colqwen:
        blocked = {
            "schema_version": "dsvire.cycle-v5-colqwen-block.v1",
            "candidate": "pinned ColQwen2-2B crop BM25+dense/RRF+MaxSim",
            "detected_vram_mb": vram,
            "device": args.colqwen_device,
            "ran": False,
            "reason": "ColQwen2 skipped by operator flag",
        }
        (results / "cycle-v5-colqwen-blocked.json").write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(blocked, indent=2, sort_keys=True))
    elif weights.is_file():
        _run_colqwen(
            python,
            registry=registry,
            queries=queries,
            model_root=colqwen_root,
            cache_root=cache_root,
            device=args.colqwen_device,
            results=results,
        )
    elif args.no_acquire_model or colqwen_root.exists():
        blocked = {
            "schema_version": "dsvire.cycle-v5-colqwen-block.v1",
            "candidate": "pinned ColQwen2-2B crop BM25+dense/RRF+MaxSim",
            "detected_vram_mb": vram,
            "device": args.colqwen_device,
            "ran": False,
            "reason": (
                "pinned ColQwen2 snapshot is not materialized; run scripts/acquire_model.py "
                "--manifest evaluation/models/colqwen2-v1.0-hf.json "
                "--destination .cache/colqwen2-offline. Scores were not invented."
            ),
        }
        (results / "cycle-v5-colqwen-blocked.json").write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(blocked, indent=2, sort_keys=True))
    else:
        _run(
            [
                python,
                "scripts/acquire_model.py",
                "--manifest",
                str(COLQWEN_MANIFEST),
                "--destination",
                str(colqwen_root),
            ]
        )
        _run_colqwen(
            python,
            registry=registry,
            queries=queries,
            model_root=colqwen_root,
            cache_root=cache_root,
            device=args.colqwen_device,
            results=results,
        )
    if not args.also_colsmol:
        return 0
    model_root = args.colsmol_model_root
    if model_root is None:
        candidate = ROOT / ".cache" / "colsmol-offline"
        if (candidate / "base" / "model.safetensors").is_file():
            model_root = candidate
    if args.skip_colsmol:
        blocked = {
            "schema_version": "dsvire.cycle-v5-colsmol-block.v1",
            "candidate": "pinned ColSmol crop BM25+dense/RRF+MaxSim",
            "detected_vram_mb": vram,
            "device": args.colsmol_device,
            "ran": False,
            "reason": "ColSmol skipped by operator flag",
        }
        (results / "cycle-v5-colsmol-blocked.json").write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 0
    if model_root is None or not (model_root / "base" / "model.safetensors").is_file():
        blocked = {
            "schema_version": "dsvire.cycle-v5-colsmol-block.v1",
            "candidate": "pinned ColSmol crop BM25+dense/RRF+MaxSim",
            "detected_vram_mb": vram,
            "device": args.colsmol_device,
            "ran": False,
            "reason": (
                "pinned ColSmol snapshot is not materialized; run scripts/acquire_model.py "
                "then re-run with --colsmol-model-root. Scores were not invented."
            ),
        }
        (results / "cycle-v5-colsmol-blocked.json").write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 0
    for split in ("calibration", "evaluation"):
        _run(
            [
                python,
                "scripts/evaluate_full_corpus_colsmol.py",
                "--registry",
                str(registry),
                "--queries",
                str(queries),
                "--model-root",
                str(model_root),
                "--cache-root",
                str(cache_root),
                "--offline",
                "--device",
                args.colsmol_device,
                "--split",
                split,
                "--json-out",
                str(results / f"cycle-v5-colsmol-{split}.json"),
                "--ranking-out",
                str(results / f"cycle-v5-colsmol-{split}-rankings.json"),
            ]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

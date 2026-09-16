"""Operator CLI for cycle v4, corpus audit, training checks, and ablation gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .ablation_gates import AblationGateError, evaluate_ablation_gates
from .cycle_execution import CycleExecutionError, inspect_cycle_v4, inspect_cycle_v5
from .sealed_holdout import load_sealed_holdout
from .training_corpus import TrainingCorpusError, audit_corpus, load_corpus_jsonl
from .training_runtime import PRODUCTION_PROFILE, bind_run


def add_training_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cycle = commands.add_parser(
        "cycle-v4-status", help="inspect frozen cycle v4; never authors queries or scores"
    )
    cycle.add_argument("--source-manifest", type=Path)
    cycle.add_argument("--seal", type=Path)
    cycle.add_argument("--submission", type=Path)
    cycle5 = commands.add_parser(
        "cycle-v5-status", help="inspect cycle v5 (MMA8451Q replaced); never authors queries"
    )
    cycle5.add_argument("--source-manifest", type=Path)
    cycle5.add_argument("--seal", type=Path)
    cycle5.add_argument("--submission", type=Path)
    corpus = commands.add_parser("corpus-audit", help="audit a training corpus.jsonl for leakage")
    corpus.add_argument("manifest", type=Path)
    train = commands.add_parser(
        "training-bind", help="bind a smoke or production training run and refuse leaked GPUs"
    )
    train.add_argument("--run-id", required=True)
    train.add_argument("--scale", choices=("smoke", "production"), required=True)
    train.add_argument("--corpus-sha256", required=True)
    train.add_argument("--model-sha256", required=True)
    train.add_argument("--runtime-sha256", required=True)
    train.add_argument("--vram-mb", type=int)
    train.add_argument("--max-steps", type=int, default=1)
    gates = commands.add_parser("ablation-gates", help="evaluate frozen Technical Bible SLOs")
    gates.add_argument("evidence", type=Path)


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CycleExecutionError(f"{path} is not a JSON object")
    return value


def run_training_command(args: argparse.Namespace) -> int:
    if args.command == "cycle-v4-status":
        inspector = inspect_cycle_v4
    elif args.command == "cycle-v5-status":
        inspector = inspect_cycle_v5
    else:
        inspector = None
    if inspector is not None:
        status = inspector(
            source_manifest=_load_json(args.source_manifest),
            seal=_load_json(args.seal),
            submission=_load_json(args.submission),
        )
        print(json.dumps(status.as_dict(), indent=2))
        return 0 if status.sources_complete else 2
    if args.command == "corpus-audit":
        records = load_corpus_jsonl(args.manifest)
        report = audit_corpus(records)
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "training-bind":
        holdout = load_sealed_holdout()
        profile = "index.gpu.smoke" if args.scale == "smoke" else PRODUCTION_PROFILE
        run = bind_run(
            run_id=args.run_id,
            scale=args.scale,
            accelerator_profile=profile,
            corpus_sha256=args.corpus_sha256,
            model_sha256=args.model_sha256,
            runtime_sha256=args.runtime_sha256,
            holdout=holdout,
            max_steps=args.max_steps,
            detected_vram_mb=args.vram_mb,
        )
        print(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "scale": run.scale,
                    "accelerator_profile": run.accelerator_profile,
                    "sealed_holdout_sha256": run.sealed_holdout_sha256,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "ablation-gates":
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        if not isinstance(evidence, dict):
            raise AblationGateError("evidence must be a JSON object")
        print(json.dumps(evaluate_ablation_gates(evidence), indent=2))
        return 0
    raise TrainingCorpusError(f"unsupported command {args.command}")

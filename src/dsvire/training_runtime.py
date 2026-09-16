"""Production training run contract: digests, leakage, checkpoints, smoke vs GPU profile."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .sealed_holdout import SealedHoldout, leakage_hits

RUN_VERSION = "dsvire.training-run.v1"
PRODUCTION_PROFILE = "index.gpu.standard"
SMOKE_PROFILE = "index.gpu.smoke"
PRODUCTION_VRAM_MB_MIN = 20_480
SMOKE_VRAM_MB_MAX = 8_192
Scale = Literal["smoke", "production"]


class TrainingRunError(ValueError):
    """The training campaign violated its reproducibility or leakage contract."""


@dataclass(frozen=True)
class TrainingRun:
    run_id: str
    scale: Scale
    accelerator_profile: str
    corpus_sha256: str
    model_sha256: str
    runtime_sha256: str
    sealed_holdout_sha256: str
    max_steps: int
    microbatch_size: int
    gradient_accumulation: int
    heartbeat_seconds: int
    idle_shutdown_seconds: int


def _sha(value: str, context: str) -> str:
    digest = value.strip().casefold()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise TrainingRunError(f"{context} must be lowercase SHA-256")
    return digest


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def bind_run(
    *,
    run_id: str,
    scale: Scale,
    accelerator_profile: str,
    corpus_sha256: str,
    model_sha256: str,
    runtime_sha256: str,
    holdout: SealedHoldout,
    max_steps: int,
    microbatch_size: int = 1,
    gradient_accumulation: int = 8,
    heartbeat_seconds: int = 30,
    idle_shutdown_seconds: int = 900,
    detected_vram_mb: int | None = None,
) -> TrainingRun:
    if not run_id.strip() or "/" in run_id or "\\" in run_id:
        raise TrainingRunError("run_id must be a path-safe token")
    if max_steps < 1 or max_steps > 1_000_000:
        raise TrainingRunError("max_steps is outside 1..=1000000")
    if microbatch_size < 1 or microbatch_size > 64:
        raise TrainingRunError("microbatch_size is outside 1..=64")
    if gradient_accumulation < 1 or gradient_accumulation > 1024:
        raise TrainingRunError("gradient_accumulation is outside 1..=1024")
    if scale == "production":
        if accelerator_profile != PRODUCTION_PROFILE:
            raise TrainingRunError("production training requires index.gpu.standard")
        if detected_vram_mb is not None and detected_vram_mb < PRODUCTION_VRAM_MB_MIN:
            raise TrainingRunError("this GPU is below the production 24GB-class profile")
    elif scale == "smoke":
        if accelerator_profile != SMOKE_PROFILE:
            raise TrainingRunError("smoke training requires index.gpu.smoke")
        if detected_vram_mb is not None and detected_vram_mb > SMOKE_VRAM_MB_MAX:
            raise TrainingRunError("smoke profile cannot bind a production-class GPU accidentally")
    else:
        raise TrainingRunError("scale must be smoke or production")
    holdout_digest = canonical_sha256(
        {
            "urls": sorted(holdout.urls),
            "hashes": sorted(holdout.content_sha256),
            "families": sorted(holdout.family_ids),
        }
    )
    return TrainingRun(
        run_id=run_id.strip(),
        scale=scale,
        accelerator_profile=accelerator_profile,
        corpus_sha256=_sha(corpus_sha256, "corpus_sha256"),
        model_sha256=_sha(model_sha256, "model_sha256"),
        runtime_sha256=_sha(runtime_sha256, "runtime_sha256"),
        sealed_holdout_sha256=holdout_digest,
        max_steps=max_steps,
        microbatch_size=microbatch_size,
        gradient_accumulation=gradient_accumulation,
        heartbeat_seconds=heartbeat_seconds,
        idle_shutdown_seconds=idle_shutdown_seconds,
    )


def reject_leaked_samples(
    sample_ids: Sequence[str],
    *,
    holdout: SealedHoldout,
    urls: Mapping[str, str] | None = None,
    hashes: Mapping[str, str] | None = None,
) -> None:
    leaked: list[str] = []
    for sample in sample_ids:
        hits = leakage_hits(
            holdout,
            url=None if urls is None else urls.get(sample),
            content_sha256=None if hashes is None else hashes.get(sample),
            family_id=sample,
            identity_text=(sample,),
        )
        if hits:
            leaked.append(f"{sample}:{','.join(hits)}")
    if leaked:
        raise TrainingRunError(
            "training samples overlap sealed evaluation: " + "; ".join(leaked[:12])
        )


def write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), indent=2).encode()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_checkpoint(
    directory: Path, run: TrainingRun, step: int, metrics: Mapping[str, float]
) -> Path:
    if step < 0 or step > run.max_steps:
        raise TrainingRunError("checkpoint step is outside the bound run")
    payload = {
        "schema_version": RUN_VERSION,
        "run_id": run.run_id,
        "scale": run.scale,
        "accelerator_profile": run.accelerator_profile,
        "step": step,
        "corpus_sha256": run.corpus_sha256,
        "model_sha256": run.model_sha256,
        "runtime_sha256": run.runtime_sha256,
        "sealed_holdout_sha256": run.sealed_holdout_sha256,
        "metrics": {key: float(value) for key, value in metrics.items()},
    }
    payload["checkpoint_sha256"] = canonical_sha256(payload)
    path = directory / run.run_id / f"step-{step:08d}.json"
    write_atomic(path, payload)
    write_atomic(directory / run.run_id / "latest.json", {"step": step, "path": path.name})
    return path


def write_heartbeat(directory: Path, run: TrainingRun, step: int) -> Path:
    path = directory / run.run_id / "heartbeat.json"
    write_atomic(path, {"run_id": run.run_id, "step": step, "status": "running"})
    return path


TrainStep = Callable[[Sequence[str], TrainingRun], dict[str, float]]


def run_steps(
    run: TrainingRun,
    batches: Sequence[Sequence[str]],
    step_fn: TrainStep,
    *,
    holdout: SealedHoldout,
    hashes: Mapping[str, str],
    checkpoint_dir: Path,
) -> Path:
    latest = Path()
    for step, batch in enumerate(batches, start=1):
        if step > run.max_steps:
            break
        reject_leaked_samples(batch, holdout=holdout, hashes=hashes)
        metrics = step_fn(batch, run)
        write_heartbeat(checkpoint_dir, run, step)
        latest = write_checkpoint(checkpoint_dir, run, step, metrics)
    return latest

"""Shared Accelerate placement for offline visual retrievers. No disk offload."""

from __future__ import annotations

from typing import Any

ALLOWED_DEVICES = {"cpu", "cuda", "auto"}
AUTO_CPU_MEMORY = "48GiB"


class VisionDeviceMapError(RuntimeError):
    """Requested device placement is unavailable or outside the allow-list."""


def resolve_vision_load_plan(torch: Any, device: str) -> dict[str, Any]:
    """Place weights with Accelerate auto-map: GPU first, then CPU RAM. No disk."""
    if device not in ALLOWED_DEVICES:
        raise VisionDeviceMapError("device must be cpu, cuda, or auto")
    if device == "cpu":
        return {
            "requested": "cpu",
            "device_map": "cpu",
            "dtype": torch.float32,
            "max_memory": None,
        }
    cuda_available = bool(torch.cuda.is_available())
    if device == "cuda":
        if not cuda_available:
            raise VisionDeviceMapError("CUDA was requested but is unavailable")
        return {
            "requested": "cuda",
            "device_map": "cuda",
            "dtype": torch.float16,
            "max_memory": None,
        }
    if not cuda_available:
        return {
            "requested": "auto",
            "device_map": "cpu",
            "dtype": torch.float32,
            "max_memory": None,
        }
    total = int(torch.cuda.get_device_properties(0).total_memory)
    reserved = max(total * 3 // 10, 384 * 1024 * 1024)
    gpu_budget = max(total - reserved, 256 * 1024 * 1024)
    return {
        "requested": "auto",
        "device_map": "auto",
        "dtype": torch.float16,
        "max_memory": {0: gpu_budget, "cpu": AUTO_CPU_MEMORY},
    }


def primary_input_device(model: Any, torch: Any, device: str) -> Any:
    """Send processor batches to the first device Accelerate placed."""
    if device in {"cpu", "cuda"}:
        return torch.device(device)
    device_map = getattr(model, "hf_device_map", None)
    if isinstance(device_map, dict) and device_map:
        first = next(iter(device_map.values()))
        if first in {"cpu", "disk"}:
            return torch.device("cpu")
        if isinstance(first, int):
            return torch.device(f"cuda:{first}")
        return torch.device(str(first))
    try:
        return next(model.parameters()).device
    except StopIteration:
        return torch.device("cpu")


def json_safe_load_plan(plan: dict[str, Any]) -> dict[str, Any]:
    safe = dict(plan)
    safe["dtype"] = str(safe["dtype"])
    memory = safe.get("max_memory")
    if isinstance(memory, dict):
        safe["max_memory"] = {str(key): value for key, value in memory.items()}
    return safe

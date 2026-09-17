"""Pinned, offline ColQwen2-2B multi-vector encoder."""

from __future__ import annotations

import hashlib
import inspect
import math
import os
from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from packaging.version import Version

from .model_manifest import ModelManifest, ModelManifestError, verify_snapshot
from .vision_device_map import (
    ALLOWED_DEVICES,
    VisionDeviceMapError,
    json_safe_load_plan,
    primary_input_device,
    resolve_vision_load_plan,
)

MAX_QUERY_BYTES = 8_192
MAX_BATCH = 4
MAX_IMAGE_TOKENS = 8_192
MAX_QUERY_TOKENS = 512


class ColQwenEncoderError(RuntimeError):
    """The pinned offline ColQwen2 encoder failed or violated its tensor contract."""


def resolve_colqwen_load_plan(torch: Any, device: str) -> dict[str, Any]:
    try:
        return resolve_vision_load_plan(torch, device)
    except VisionDeviceMapError as exc:
        raise ColQwenEncoderError(str(exc)) from exc


def _require_runtime(manifest: ModelManifest) -> None:
    package_names = {
        "transformers": "transformers",
        "huggingface_hub": "huggingface-hub",
        "torch": "torch",
        "torchvision": "torchvision",
    }
    for field, package in package_names.items():
        expected = manifest.runtime.get(field)
        observed = Version(version(package))
        if not isinstance(expected, str) or observed.public != Version(expected).public:
            raise ColQwenEncoderError(f"{package} runtime differs from the model manifest")


def _vectors(
    value: Any, *, batch: int, dimension: int, token_limit: int, context: str
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    shape = tuple(int(item) for item in value.shape)
    if (
        len(shape) != 3
        or shape[0] != batch
        or not 1 <= shape[1] <= token_limit
        or shape[2] != dimension
    ):
        raise ColQwenEncoderError(f"{context} tensor shape is invalid")
    rows = value.detach().float().cpu().tolist()
    result: list[tuple[tuple[float, ...], ...]] = []
    for document in rows:
        tokens: list[tuple[float, ...]] = []
        for token in document:
            vector = tuple(float(item) for item in token)
            if len(vector) != dimension or not all(math.isfinite(item) for item in vector):
                raise ColQwenEncoderError(f"{context} contains invalid vectors")
            tokens.append(vector)
        result.append(tuple(tokens))
    return tuple(result)


def _embeddings(encoded: Any) -> Any:
    embeddings = getattr(encoded, "embeddings", None)
    if embeddings is None:
        raise ColQwenEncoderError("ColQwen2 forward did not return multi-vector embeddings")
    return embeddings


def _process_images(processor: Any, images: Sequence[Any]) -> Any:
    if hasattr(processor, "process_images"):
        return processor.process_images(list(images))
    return processor(images=list(images), return_tensors="pt")


def _process_queries(processor: Any, queries: Sequence[str]) -> Any:
    if hasattr(processor, "process_queries"):
        return processor.process_queries(list(queries))
    return processor(text=list(queries), return_tensors="pt")


def _masked(encoded: Any, batch: Any) -> Any:
    embeddings = _embeddings(encoded)
    mask = None
    if hasattr(batch, "get"):
        mask = batch.get("attention_mask")
    if mask is None:
        mask = getattr(batch, "attention_mask", None)
    if mask is None:
        return embeddings
    return embeddings * mask.unsqueeze(-1)


class ColQwenEncoder:
    """Encode crop pixels and raw queries with verified local ColQwen2 bytes only."""

    def __init__(self, manifest: ModelManifest, model_root: Path, *, device: str = "cpu") -> None:
        if device not in ALLOWED_DEVICES:
            raise ColQwenEncoderError("device must be cpu, cuda, or auto")
        if manifest.runtime.get("encoder") != "colqwen2":
            raise ColQwenEncoderError("manifest encoder must be colqwen2")
        if manifest.runtime.get("model") != "ColQwen2ForRetrieval":
            raise ColQwenEncoderError("manifest model must be ColQwen2ForRetrieval")
        repositories = {repository.name: repository for repository in manifest.repositories}
        if set(repositories) != {"weights"}:
            raise ColQwenEncoderError("manifest must contain a single weights repository")
        weights = model_root / "weights"
        try:
            verify_snapshot(repositories["weights"], weights)
        except ModelManifestError as exc:
            raise ColQwenEncoderError("offline ColQwen2 snapshot verification failed") from exc
        _require_runtime(manifest)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        try:
            torch: Any = import_module("torch")
            transformers: Any = import_module("transformers")
        except ImportError as exc:
            raise ColQwenEncoderError("install the pinned ColQwen runtime profile") from exc
        model_type = getattr(transformers, "ColQwen2ForRetrieval", None)
        processor_type = getattr(transformers, "ColQwen2Processor", None)
        if model_type is None or processor_type is None:
            raise ColQwenEncoderError(
                "pinned transformers does not expose ColQwen2ForRetrieval/ColQwen2Processor"
            )
        plan = resolve_colqwen_load_plan(torch, device)
        if plan["device_map"] == "auto":
            try:
                import_module("accelerate")
            except ImportError as exc:
                raise ColQwenEncoderError(
                    "device_map=auto requires the pinned accelerate runtime"
                ) from exc
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            if torch.get_num_interop_threads() != 1:
                raise ColQwenEncoderError(
                    "Torch inter-op thread policy could not be applied"
                ) from None
        load_kwargs: dict[str, Any] = {
            "torch_dtype": plan["dtype"],
            "device_map": plan["device_map"],
            "attn_implementation": "eager",
            "local_files_only": True,
            "low_cpu_mem_usage": True,
        }
        if plan["max_memory"] is not None:
            load_kwargs["max_memory"] = dict(plan["max_memory"])
        try:
            self._model = model_type.from_pretrained(weights, **load_kwargs).eval()
            self._processor = processor_type.from_pretrained(weights, local_files_only=True)
        except ColQwenEncoderError:
            raise
        except Exception as exc:
            raise ColQwenEncoderError("offline ColQwen2 load failed") from exc
        self._torch = torch
        self._device = device
        self._load_plan = plan
        self.hf_device_map = dict(getattr(self._model, "hf_device_map", None) or {})
        self._input_device = primary_input_device(self._model, torch, device)
        dimension = manifest.runtime.get("embedding_dimension")
        if (
            isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or not 1 <= dimension <= 8_192
        ):
            raise ColQwenEncoderError("embedding dimension is invalid")
        self.dimension = dimension
        self.model_id = manifest.id
        self.model_sha256 = manifest.content_sha256

    @property
    def load_plan(self) -> dict[str, Any]:
        return json_safe_load_plan(self._load_plan)

    @property
    def implementation_sha256(self) -> str:
        source = "\n".join(
            inspect.getsource(component).replace("\r\n", "\n")
            for component in (
                ColQwenEncoder,
                resolve_colqwen_load_plan,
                resolve_vision_load_plan,
                primary_input_device,
                _vectors,
                _embeddings,
                _masked,
                _process_images,
                _process_queries,
                _require_runtime,
            )
        )
        runtime = "\n".join(
            f"{name}={version(name)}"
            for name in ("transformers", "torch", "torchvision", "Pillow")
        )
        return hashlib.sha256(f"{source}\n{runtime}".encode()).hexdigest()

    def encode_images(self, images: Sequence[Any]) -> tuple[tuple[tuple[float, ...], ...], ...]:
        if not 1 <= len(images) <= MAX_BATCH:
            raise ColQwenEncoderError("image batch is outside its bounded range")
        try:
            batch = _process_images(self._processor, images).to(self._input_device)
            with self._torch.inference_mode():
                encoded = self._model(**batch)
            return _vectors(
                _masked(encoded, batch),
                batch=len(images),
                dimension=self.dimension,
                token_limit=MAX_IMAGE_TOKENS,
                context="image",
            )
        except ColQwenEncoderError:
            raise
        except Exception as exc:
            raise ColQwenEncoderError(_inference_failure("image", exc)) from exc

    def encode_queries(self, queries: Sequence[str]) -> tuple[tuple[tuple[float, ...], ...], ...]:
        if not 1 <= len(queries) <= MAX_BATCH or any(
            not query.strip() or len(query.encode()) > MAX_QUERY_BYTES for query in queries
        ):
            raise ColQwenEncoderError("query batch is outside its bounded range")
        try:
            batch = _process_queries(self._processor, queries).to(self._input_device)
            with self._torch.inference_mode():
                encoded = self._model(**batch)
            return _vectors(
                _masked(encoded, batch),
                batch=len(queries),
                dimension=self.dimension,
                token_limit=MAX_QUERY_TOKENS,
                context="query",
            )
        except ColQwenEncoderError:
            raise
        except Exception as exc:
            raise ColQwenEncoderError(_inference_failure("query", exc)) from exc


def _inference_failure(kind: str, exc: BaseException) -> str:
    text = str(exc).casefold()
    if isinstance(exc, MemoryError) or "out of memory" in text:
        return (
            f"ColQwen2 {kind} inference ran out of memory under the selected device map; "
            "fail closed, scores were not invented"
        )
    return f"ColQwen2 {kind} inference failed"

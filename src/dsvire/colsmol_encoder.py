"""Pinned, offline ColSmol multi-vector encoder adapter."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .model_manifest import (
    ModelManifest,
    ModelManifestError,
    verify_materialized_adapter_config,
    verify_snapshot,
)

MAX_QUERY_BYTES = 8_192
MAX_BATCH = 4
MAX_IMAGE_TOKENS = 4_096
MAX_QUERY_TOKENS = 512
QUERY_SUFFIX = "<end_of_utterance>" * 10
QUERY_SENTINEL = "What is shown in the image?"
QUERY_SENTINEL_IDS = (
    22731,
    42,
    1812,
    314,
    3057,
    281,
    260,
    2443,
    47,
    *(49279 for _ in range(10)),
    198,
)


def _query_text(query: str) -> str:
    return f"Query: {query}{QUERY_SUFFIX}\n"


class ColSmolEncoderError(RuntimeError):
    """The pinned offline encoder failed or violated its tensor contract."""


def _require_runtime(manifest: ModelManifest) -> None:
    package_names = {
        "transformers": "transformers",
        "peft": "peft",
        "huggingface_hub": "huggingface-hub",
        "torch": "torch",
        "torchvision": "torchvision",
    }
    for field, package in package_names.items():
        expected = manifest.runtime.get(field)
        if not isinstance(expected, str) or version(package) != expected:
            raise ColSmolEncoderError(f"{package} runtime differs from the model manifest")


def _runtime_types(torch: Any, transformers: Any) -> tuple[type[Any], type[Any]]:
    """Build the minimal audited ColSmol model and processor on public HF APIs."""

    class TokitoColIdefics3(transformers.Idefics3PreTrainedModel):  # type: ignore[misc]
        main_input_name = "doc_input_ids"

        def __init__(self, config: Any) -> None:
            super().__init__(config=config)
            self.model = transformers.Idefics3Model(config)
            self.linear = torch.nn.Linear(self.model.config.text_config.hidden_size, 128)
            self.post_init()

        def forward(self, *args: Any, **kwargs: Any) -> Any:
            hidden = self.model(*args, **kwargs)[0]
            projected = self.linear(hidden)
            projected = projected / projected.norm(dim=-1, keepdim=True)
            return projected * kwargs["attention_mask"].unsqueeze(-1)

    class TokitoColIdefics3Processor(transformers.Idefics3Processor):  # type: ignore[misc]
        def process_images(self, images: Sequence[Any]) -> Any:
            nested = [[image.convert("RGB")] for image in images]
            texts = []
            for _image in nested:
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe the image."},
                            {"type": "image"},
                        ],
                    }
                ]
                texts.append(
                    self.apply_chat_template(messages, add_generation_prompt=False).strip()
                )
            return self(text=texts, images=nested, return_tensors="pt", padding="longest")

        def process_queries(self, queries: Sequence[str]) -> Any:
            texts = [_query_text(query) for query in queries]
            return self.tokenizer(text=texts, return_tensors="pt", padding="longest")

    return TokitoColIdefics3, TokitoColIdefics3Processor


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
        raise ColSmolEncoderError(f"{context} tensor shape is invalid")
    rows = value.detach().float().cpu().tolist()
    result: list[tuple[tuple[float, ...], ...]] = []
    for document in rows:
        tokens: list[tuple[float, ...]] = []
        for token in document:
            vector = tuple(float(item) for item in token)
            if len(vector) != dimension or not all(math.isfinite(item) for item in vector):
                raise ColSmolEncoderError(f"{context} contains invalid vectors")
            tokens.append(vector)
        result.append(tuple(tokens))
    return tuple(result)


class ColSmolEncoder:
    """Encode crop pixels and raw queries with verified local model bytes only."""

    def __init__(self, manifest: ModelManifest, model_root: Path, *, device: str = "cpu") -> None:
        if device not in {"cpu", "cuda"}:
            raise ColSmolEncoderError("device must be cpu or cuda")
        repositories = {repository.name: repository for repository in manifest.repositories}
        if set(repositories) != {"adapter", "base"}:
            raise ColSmolEncoderError("manifest must contain adapter and base repositories")
        try:
            verify_snapshot(repositories["base"], model_root / "base")
        except ModelManifestError as exc:
            raise ColSmolEncoderError("offline base snapshot verification failed") from exc
        # adapter_config is deliberately rewritten during materialization, so verify every other adapter byte.
        adapter = repositories["adapter"]
        rewritten = type(adapter)(
            adapter.name,
            adapter.repository,
            adapter.revision,
            adapter.license,
            tuple(file for file in adapter.files if file.path != "adapter_config.json"),
        )
        try:
            verify_snapshot(
                rewritten,
                model_root / "adapter",
                ignored_files=frozenset({"adapter_config.json"}),
            )
            verify_materialized_adapter_config(manifest, model_root)
        except ModelManifestError as exc:
            raise ColSmolEncoderError("offline adapter snapshot verification failed") from exc
        _require_runtime(manifest)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        try:
            torch: Any = import_module("torch")
            transformers: Any = import_module("transformers")
            peft: Any = import_module("peft")
        except ImportError as exc:
            raise ColSmolEncoderError("install the pinned ColSmol runtime profile") from exc
        if device == "cuda" and not torch.cuda.is_available():
            raise ColSmolEncoderError("CUDA was requested but is unavailable")
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            if torch.get_num_interop_threads() != 1:
                raise ColSmolEncoderError(
                    "Torch inter-op thread policy could not be applied"
                ) from None
        dtype = torch.float16 if device == "cuda" else torch.float32
        model_type, processor_type = _runtime_types(torch, transformers)
        try:
            base_model = model_type.from_pretrained(
                model_root / "base",
                torch_dtype=dtype,
                device_map=device,
                attn_implementation="eager",
                local_files_only=True,
            )
            self._model = peft.PeftModel.from_pretrained(
                base_model,
                model_root / "adapter",
                is_trainable=False,
                local_files_only=True,
            ).eval()
            image_processor = transformers.Idefics3ImageProcessorPil.from_pretrained(
                model_root / "base", local_files_only=True
            )
            tokenizer = transformers.AutoTokenizer.from_pretrained(
                model_root / "base", local_files_only=True
            )
            self._processor = processor_type(
                image_processor=image_processor,
                tokenizer=tokenizer,
                image_seq_len=64,
                chat_template=json.loads(
                    (model_root / "base" / "chat_template.json").read_text(encoding="utf-8")
                )["chat_template"],
            )
            sentinel_ids = tuple(self._processor.tokenizer(_query_text(QUERY_SENTINEL)).input_ids)
            if sentinel_ids != QUERY_SENTINEL_IDS:
                raise ColSmolEncoderError("ColSmol tokenizer contract drifted")
        except Exception as exc:
            raise ColSmolEncoderError("offline ColSmol load failed") from exc
        self._torch = torch
        self._device = device
        dimension = manifest.runtime.get("embedding_dimension")
        if (
            isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or not 1 <= dimension <= 8_192
        ):
            raise ColSmolEncoderError("embedding dimension is invalid")
        self.dimension = dimension
        self.model_id = manifest.id
        self.model_sha256 = manifest.content_sha256

    @property
    def implementation_sha256(self) -> str:
        source = "\n".join(
            inspect.getsource(component).replace("\r\n", "\n")
            for component in (
                ColSmolEncoder,
                _vectors,
                _require_runtime,
                _runtime_types,
                _query_text,
            )
        )
        runtime = "\n".join(
            f"{name}={version(name)}"
            for name in ("transformers", "peft", "torch", "torchvision", "Pillow")
        )
        return hashlib.sha256(f"{source}\n{runtime}".encode()).hexdigest()

    def encode_images(self, images: Sequence[Any]) -> tuple[tuple[tuple[float, ...], ...], ...]:
        if not 1 <= len(images) <= MAX_BATCH:
            raise ColSmolEncoderError("image batch is outside its bounded range")
        try:
            batch = self._processor.process_images(list(images)).to(self._device)
            with self._torch.inference_mode():
                encoded = self._model(**batch)
            return _vectors(
                encoded,
                batch=len(images),
                dimension=self.dimension,
                token_limit=MAX_IMAGE_TOKENS,
                context="image",
            )
        except ColSmolEncoderError:
            raise
        except Exception as exc:
            raise ColSmolEncoderError("ColSmol image inference failed") from exc

    def encode_queries(self, queries: Sequence[str]) -> tuple[tuple[tuple[float, ...], ...], ...]:
        if not 1 <= len(queries) <= MAX_BATCH or any(
            not query.strip() or len(query.encode()) > MAX_QUERY_BYTES for query in queries
        ):
            raise ColSmolEncoderError("query batch is outside its bounded range")
        try:
            batch = self._processor.process_queries(list(queries)).to(self._device)
            with self._torch.inference_mode():
                encoded = self._model(**batch)
            return _vectors(
                encoded,
                batch=len(queries),
                dimension=self.dimension,
                token_limit=MAX_QUERY_TOKENS,
                context="query",
            )
        except ColSmolEncoderError:
            raise
        except Exception as exc:
            raise ColSmolEncoderError("ColSmol query inference failed") from exc

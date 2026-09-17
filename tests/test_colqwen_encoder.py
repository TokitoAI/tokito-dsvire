from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from dsvire.colqwen_encoder import (
    ColQwenEncoderError,
    _embeddings,
    _masked,
    _process_images,
    _process_queries,
    _vectors,
    resolve_colqwen_load_plan,
)
from dsvire.model_manifest import load_model_manifest, materialize_offline_model

ROOT = Path(__file__).parents[1]


class _Tensor:
    def __init__(self, value: Any, shape: tuple[int, ...]) -> None:
        self.value = value
        self.shape = shape

    def detach(self) -> _Tensor:
        return self

    def float(self) -> _Tensor:
        return self

    def cpu(self) -> _Tensor:
        return self

    def tolist(self) -> Any:
        return self.value

    def unsqueeze(self, dim: int) -> _Tensor:
        assert dim == -1
        return self

    def __mul__(self, other: Any) -> _Tensor:
        return self


class _FakeCuda:
    def __init__(self, available: bool, total_memory: int = 0) -> None:
        self._available = available
        self._total = total_memory

    def is_available(self) -> bool:
        return self._available

    def get_device_properties(self, index: int) -> Any:
        assert index == 0
        return type("Props", (), {"total_memory": self._total})()


class _FakeTorch:
    def __init__(self, *, cuda: _FakeCuda, float16: str = "fp16", float32: str = "fp32") -> None:
        self.cuda = cuda
        self.float16 = float16
        self.float32 = float32


def test_committed_colqwen_manifest_is_valid_and_binds_expected_weights() -> None:
    raw = json.loads((ROOT / "evaluation/models/colqwen2-v1.0-hf.json").read_text())
    schema = json.loads((ROOT / "scripts/schema/model_manifest_v1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    manifest = load_model_manifest(raw)
    files = {file.path: file for file in manifest.repositories[0].files}
    assert manifest.repositories[0].name == "weights"
    assert manifest.repositories[0].revision == "ddc07d2317c80f75fc742b7362ee9ad1912908f9"
    assert (
        files["model.safetensors"].sha256
        == "2f6dbf32fc2db5b045d74ae73b148425d6e03cc1106a047cdcc7e72b6dc53aba"
    )
    assert files["model.safetensors"].bytes == 4418454832
    assert manifest.runtime["encoder"] == "colqwen2"
    assert manifest.runtime["embedding_dimension"] == 128
    assert "adapter_config_semantic_sha256" not in manifest.runtime


def test_materialize_single_weights_repository(tmp_path: Path) -> None:
    payload = b"colqwen-weights"
    raw = {
        "schema_version": "dsvire.model-manifest.v1",
        "id": "test/colqwen@" + "a" * 40,
        "license": "Apache-2.0",
        "repositories": [
            {
                "name": "weights",
                "repository": "test/colqwen",
                "revision": "a" * 40,
                "license": "Apache-2.0",
                "files": [
                    {
                        "path": "config.json",
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
        ],
        "runtime": {"encoder": "colqwen2"},
    }
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.json").write_bytes(payload)
    destination = tmp_path / "offline"
    weights = materialize_offline_model(load_model_manifest(raw), {"weights": source}, destination)
    assert weights == destination / "weights"
    assert (weights / "config.json").read_bytes() == payload


def test_colqwen_auto_plan_uses_gpu_then_cpu_ram() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(True, total_memory=12 * 1024 * 1024 * 1024))
    plan = resolve_colqwen_load_plan(torch, "auto")
    assert plan["device_map"] == "auto"
    assert plan["dtype"] == "fp16"
    assert plan["max_memory"]["cpu"] == "48GiB"


def test_colqwen_cuda_plan_fails_closed_without_gpu() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(False))
    with pytest.raises(ColQwenEncoderError, match="CUDA was requested"):
        resolve_colqwen_load_plan(torch, "cuda")


def test_embeddings_and_masking_are_required() -> None:
    tensor = _Tensor([[[1, 2]]], (1, 1, 2))
    encoded = type("Out", (), {"embeddings": tensor})()
    assert _embeddings(encoded) is tensor
    with pytest.raises(ColQwenEncoderError, match="multi-vector embeddings"):
        _embeddings(object())
    batch = {"attention_mask": _Tensor([[[1]]], (1, 1, 1))}
    masked = _masked(encoded, batch)
    assert masked is tensor
    assert _vectors(tensor, batch=1, dimension=2, token_limit=4, context="test") == (((1.0, 2.0),),)


def test_processor_falls_back_to_native_call() -> None:
    class Native:
        def __call__(self, **kwargs: Any) -> str:
            self.kwargs = kwargs
            return "ok"

    native = Native()
    assert _process_images(native, ["img"]) == "ok"
    assert native.kwargs == {"images": ["img"], "return_tensors": "pt"}
    queries = Native()
    assert _process_queries(queries, ["pinout"]) == "ok"
    assert queries.kwargs == {"text": ["pinout"], "return_tensors": "pt"}

    class Dedicated:
        def process_images(self, images: list[str]) -> str:
            assert images == ["img"]
            return "images"

        def process_queries(self, queries: list[str]) -> str:
            assert queries == ["pinout"]
            return "queries"

        def __call__(self, **kwargs: Any) -> str:
            raise AssertionError("native processor call must not run")

    dedicated = Dedicated()
    assert _process_images(dedicated, ["img"]) == "images"
    assert _process_queries(dedicated, ["pinout"]) == "queries"

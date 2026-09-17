from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from dsvire.colsmol_encoder import (
    QUERY_SENTINEL_IDS,
    ColSmolEncoderError,
    _query_text,
    _require_runtime,
    _vectors,
    primary_input_device,
    resolve_colsmol_load_plan,
)
from dsvire.model_manifest import ModelManifest


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


def test_vectors_validate_and_freeze_plain_float_output() -> None:
    tensor = _Tensor([[[1, 2], [3.5, 4]]], (1, 2, 2))
    assert _vectors(tensor, batch=1, dimension=2, token_limit=4, context="test") == (
        ((1.0, 2.0), (3.5, 4.0)),
    )


def test_query_template_matches_legacy_colsmol_contract() -> None:
    assert _query_text("What is shown in the image?") == (
        "Query: What is shown in the image?" + "<end_of_utterance>" * 10 + "\n"
    )
    assert (
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
    ) == QUERY_SENTINEL_IDS


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

    def device(self, name: str) -> str:
        return name


def test_auto_plan_uses_gpu_then_cpu_ram() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(True, total_memory=4 * 1024 * 1024 * 1024))
    plan = resolve_colsmol_load_plan(torch, "auto")
    assert plan["requested"] == "auto"
    assert plan["device_map"] == "auto"
    assert plan["dtype"] == "fp16"
    assert plan["max_memory"] is not None
    assert plan["max_memory"][0] < 4 * 1024 * 1024 * 1024
    assert plan["max_memory"]["cpu"] == "48GiB"
    json.dumps({str(key): value for key, value in plan["max_memory"].items()}, sort_keys=True)


def test_auto_plan_without_cuda_stays_on_cpu() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(False))
    plan = resolve_colsmol_load_plan(torch, "auto")
    assert plan["device_map"] == "cpu"
    assert plan["dtype"] == "fp32"
    assert plan["max_memory"] is None


def test_cuda_plan_fails_closed_without_gpu() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(False))
    with pytest.raises(ColSmolEncoderError, match="CUDA was requested"):
        resolve_colsmol_load_plan(torch, "cuda")


def test_unknown_device_fails_closed() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(True, total_memory=8 * 1024 * 1024 * 1024))
    with pytest.raises(ColSmolEncoderError, match="cpu, cuda, or auto"):
        resolve_colsmol_load_plan(torch, "mps")


def test_auto_inputs_follow_first_accelerate_device() -> None:
    torch = _FakeTorch(cuda=_FakeCuda(True, total_memory=4 * 1024 * 1024 * 1024))
    model = type("Model", (), {"hf_device_map": {"model.layers.0": 0, "lm_head": "cpu"}})()
    assert primary_input_device(model, torch, "auto") == "cuda:0"


def test_runtime_accepts_official_local_build_suffix() -> None:
    manifest = ModelManifest(
        "model",
        "MIT",
        (),
        {
            "transformers": "5.5.0",
            "peft": "0.19.0",
            "huggingface_hub": "1.5.0",
            "torch": "2.13.0",
            "torchvision": "0.28.0",
        },
        "a" * 64,
    )
    versions = {
        "transformers": "5.5.0",
        "peft": "0.19.0",
        "huggingface-hub": "1.5.0",
        "torch": "2.13.0+cu130",
        "torchvision": "0.28.0+cu130",
    }
    with patch("dsvire.colsmol_encoder.version", side_effect=versions.__getitem__):
        _require_runtime(manifest)


@pytest.mark.parametrize(
    "tensor,batch,dimension,limit,message",
    [
        (_Tensor([], (0, 2, 2)), 1, 2, 4, "shape"),
        (_Tensor([[[1, 2]]], (1, 5, 2)), 1, 2, 4, "shape"),
        (_Tensor([[[1, 2]]], (1, 1, 3)), 1, 2, 4, "shape"),
        (_Tensor([[[float("nan"), 2]]], (1, 1, 2)), 1, 2, 4, "invalid vectors"),
        (_Tensor([[[float("inf"), 2]]], (1, 1, 2)), 1, 2, 4, "invalid vectors"),
    ],
)
def test_vectors_fail_closed(
    tensor: _Tensor, batch: int, dimension: int, limit: int, message: str
) -> None:
    with pytest.raises(ColSmolEncoderError, match=message):
        _vectors(tensor, batch=batch, dimension=dimension, token_limit=limit, context="test")

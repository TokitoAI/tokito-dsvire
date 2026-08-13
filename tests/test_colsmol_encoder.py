from __future__ import annotations

from typing import Any

import pytest

from dsvire.colsmol_encoder import (
    QUERY_SENTINEL_IDS,
    ColSmolEncoderError,
    _query_text,
    _vectors,
)


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

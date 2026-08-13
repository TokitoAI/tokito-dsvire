"""Unscoped query-text to crop-pixel OpenCLIP baseline."""

from __future__ import annotations

import hashlib
import inspect
import io
import math
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from .pdf_backend import BACKEND_ID
from .visual_adapters import (
    OPENCLIP_MODEL_BYTES,
    OPENCLIP_MODEL_NAME,
    OPENCLIP_MODEL_SHA256,
)

SYSTEM_ID = "dsvire.query-baseline.openclip-unscoped@2.0.0"


class OpenClipQueryError(RuntimeError):
    """Pinned model inference failed or violated its output contract."""


class OpenClipQueryBaseline:
    """Scores only raw query strings against raw PNG crop bytes."""

    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file() or model_path.stat().st_size != OPENCLIP_MODEL_BYTES:
            raise OpenClipQueryError("OpenCLIP model size does not match the pinned artifact")
        with model_path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != OPENCLIP_MODEL_SHA256:
            raise OpenClipQueryError("OpenCLIP model SHA-256 does not match the pinned artifact")
        try:
            import open_clip
            import torch
        except ImportError as exc:
            raise OpenClipQueryError("install tokito-dsvire[openclip]") from exc
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            if torch.get_num_interop_threads() != 1:
                raise OpenClipQueryError(
                    "OpenCLIP inter-op thread policy could not be applied"
                ) from None
        model, _, preprocess = open_clip.create_model_and_transforms(
            OPENCLIP_MODEL_NAME, pretrained=str(model_path), device="cpu"
        )
        self._torch = torch
        self._model = model.eval()
        self._preprocess = preprocess
        self._tokenizer = open_clip.get_tokenizer(OPENCLIP_MODEL_NAME)

    @property
    def implementation_sha256(self) -> str:
        source = "\n".join(
            inspect.getsource(component).replace("\r\n", "\n")
            for component in (OpenClipQueryBaseline, _bounded_scores)
        ).encode()
        versions = (
            f"open_clip_torch={version('open_clip_torch')}\n"
            f"torch={version('torch')}\nPillow={version('Pillow')}\n{BACKEND_ID}"
        ).encode()
        return hashlib.sha256(source + versions).hexdigest()

    def rank(self, queries: Sequence[str], pngs: Sequence[bytes]) -> list[list[float]]:
        """Return one bounded, rounded cosine score row per raw query."""
        if not queries or not pngs:
            raise OpenClipQueryError("queries and crop pixels must be non-empty")
        try:
            from PIL import Image

            images = []
            for png in pngs:
                with Image.open(io.BytesIO(png)) as source:
                    images.append(self._preprocess(source.convert("RGB")))
            with self._torch.inference_mode():
                image_features = self._model.encode_image(self._torch.stack(images))
                text_features = self._model.encode_text(self._tokenizer(list(queries)))
                image_features /= image_features.norm(dim=-1, keepdim=True)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                similarities = (text_features @ image_features.T).cpu().tolist()
        except Exception as exc:
            raise OpenClipQueryError("OpenCLIP query inference failed") from exc
        return _bounded_scores(similarities, len(queries), len(pngs))


def _bounded_scores(
    similarities: Sequence[Sequence[float]], query_count: int, image_count: int
) -> list[list[float]]:
    if len(similarities) != query_count:
        raise OpenClipQueryError("OpenCLIP returned an invalid score matrix")
    rows: list[list[float]] = []
    for row in similarities:
        if len(row) != image_count:
            raise OpenClipQueryError("OpenCLIP returned an invalid score matrix")
        values: list[float] = []
        for raw in row:
            value = float(raw)
            if not math.isfinite(value) or not -1.000001 <= value <= 1.000001:
                raise OpenClipQueryError("OpenCLIP returned an invalid cosine similarity")
            values.append(round(min(1.0, max(0.0, (value + 1.0) / 2.0)), 5))
        rows.append(values)
    return rows

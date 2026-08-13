from __future__ import annotations

import io
from email.message import Message
from pathlib import Path
from types import TracebackType
from urllib.error import URLError
from urllib.request import Request

import pytest

from dsvire.model_acquire import NoUnsafeRedirect, download_model_file
from dsvire.model_manifest import ModelFile, ModelManifestError, ModelRepository


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class _Opener:
    def __init__(self, data: bytes | Exception) -> None:
        self.data = data
        self.request: Request | None = None

    def open(self, request: Request, timeout: int) -> _Response:
        assert timeout == 60
        self.request = request
        if isinstance(self.data, Exception):
            raise self.data
        return _Response(self.data)


def _repository() -> ModelRepository:
    return ModelRepository("adapter", "org/model", "1" * 40, "MIT", ())


def test_download_streams_exact_verified_bytes(tmp_path: Path) -> None:
    import hashlib

    data = b"verified model bytes"
    file = ModelFile("weights.bin", len(data), hashlib.sha256(data).hexdigest())
    opener = _Opener(data)
    target = tmp_path / file.path
    download_model_file(_repository(), file, target, open_url=opener.open)
    assert target.read_bytes() == data
    assert opener.request is not None
    assert (
        opener.request.full_url
        == f"https://huggingface.co/org/model/resolve/{'1' * 40}/weights.bin"
    )


@pytest.mark.parametrize(
    "data,size,digest,message",
    [
        (b"too long", 2, "0" * 64, "exceeds expected size"),
        (b"short", 6, "0" * 64, "size or digest mismatch"),
        (b"wrong", 5, "0" * 64, "size or digest mismatch"),
    ],
)
def test_download_fails_closed_and_removes_partial(
    tmp_path: Path, data: bytes, size: int, digest: str, message: str
) -> None:
    target = tmp_path / "weights.bin"
    with pytest.raises(ModelManifestError, match=message):
        download_model_file(
            _repository(),
            ModelFile("weights.bin", size, digest),
            target,
            open_url=_Opener(data).open,
        )
    assert not target.exists()


def test_download_wraps_network_error_and_removes_partial(tmp_path: Path) -> None:
    target = tmp_path / "weights.bin"
    with pytest.raises(ModelManifestError, match="failed to download"):
        download_model_file(
            _repository(),
            ModelFile("weights.bin", 1, "0" * 64),
            target,
            open_url=_Opener(URLError("offline")).open,
        )
    assert not target.exists()


def test_redirect_handler_rejects_non_https() -> None:
    handler = NoUnsafeRedirect()
    request = Request("https://huggingface.co/model")
    with pytest.raises(ModelManifestError, match="outside HTTPS"):
        handler.redirect_request(request, None, 302, "found", Message(), "http://example.test/x")

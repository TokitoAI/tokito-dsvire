from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from dsvire.eval_download import EvaluationDownloadError, fetch_hash_pinned_pdf
from dsvire.pipeline import MAX_PDF_BYTES


def _fetch(payload: bytes, cache_dir: Path, *, offline: bool = False) -> bytes:
    return fetch_hash_pinned_pdf(
        case_id="fixture",
        source_url="https://example.invalid/fixture.pdf",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        cache_dir=cache_dir,
        offline=offline,
        retry_delay_seconds=0,
    )


def test_exact_cached_bytes_are_rehashed_before_use(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\nfixture"
    path = tmp_path / f"{hashlib.sha256(payload).hexdigest()}.pdf"
    path.write_bytes(payload)

    assert _fetch(payload, tmp_path, offline=True) == payload


def test_corrupt_cache_and_missing_offline_source_fail_closed(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\nfixture"
    path = tmp_path / f"{hashlib.sha256(payload).hexdigest()}.pdf"
    path.write_bytes(b"corrupt")

    with pytest.raises(EvaluationDownloadError, match="cached SHA-256 mismatch"):
        _fetch(payload, tmp_path, offline=True)

    path.unlink()
    with pytest.raises(EvaluationDownloadError, match="not cached in offline mode"):
        _fetch(payload, tmp_path, offline=True)


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str, content_length: str | None = None) -> None:
        super().__init__(payload)
        self._url = url
        self.headers = {} if content_length is None else {"content-length": content_length}

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_download_is_atomic_hash_pinned_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"%PDF-1.7\ndownloaded"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            payload, url="https://cdn.example.invalid/fixture.pdf", content_length=str(len(payload))
        ),
    )

    assert _fetch(payload, tmp_path) == payload
    assert list(tmp_path.glob("*.tmp")) == []
    assert (tmp_path / f"{hashlib.sha256(payload).hexdigest()}.pdf").read_bytes() == payload


@pytest.mark.parametrize(
    ("source_url", "digest", "message"),
    [
        ("http://example.invalid/a.pdf", "a" * 64, "must use HTTPS"),
        ("https://example.invalid/a.pdf", "A" * 64, "lowercase SHA-256"),
    ],
)
def test_source_contract_is_validated_before_network_access(
    tmp_path: Path, source_url: str, digest: str, message: str
) -> None:
    with pytest.raises(EvaluationDownloadError, match=message):
        fetch_hash_pinned_pdf(
            case_id="fixture",
            source_url=source_url,
            content_sha256=digest,
            cache_dir=tmp_path,
            offline=False,
        )


def test_redirect_away_from_https_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"%PDF-1.7\nredirect"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(payload, url="http://unsafe.invalid/fixture.pdf"),
    )

    with pytest.raises(EvaluationDownloadError, match="redirected away from HTTPS"):
        _fetch(payload, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_hash_mismatch_removes_partial_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = b"%PDF-1.7\nexpected"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            b"%PDF-1.7\nsubstituted", url="https://example.invalid/fixture.pdf"
        ),
    )

    with pytest.raises(EvaluationDownloadError, match="mismatch after 3 attempts"):
        _fetch(expected, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_transient_download_hash_mismatch_retries_only_until_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = b"%PDF-1.7\nexpected"
    responses = iter([b"%PDF-1.7\nsubstituted", expected])
    calls = 0

    def respond(*_args: object, **_kwargs: object) -> _Response:
        nonlocal calls
        calls += 1
        return _Response(next(responses), url="https://example.invalid/fixture.pdf")

    monkeypatch.setattr("urllib.request.urlopen", respond)

    assert _fetch(expected, tmp_path) == expected
    assert calls == 2
    assert list(tmp_path.glob("*.tmp")) == []


def test_declared_oversize_download_is_rejected_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"%PDF-1.7\nfixture"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            payload,
            url="https://example.invalid/fixture.pdf",
            content_length=str(MAX_PDF_BYTES + 1),
        ),
    )

    with pytest.raises(EvaluationDownloadError, match="declared download size exceeds"):
        _fetch(payload, tmp_path)
    assert list(tmp_path.iterdir()) == []

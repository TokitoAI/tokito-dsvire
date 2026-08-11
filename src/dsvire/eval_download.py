"""Bounded, hash-pinned downloader shared by evaluation commands."""

from __future__ import annotations

import hashlib
import math
import re
import tempfile
import time
import urllib.request
from pathlib import Path

from .pipeline import MAX_PDF_BYTES


class EvaluationDownloadError(ValueError):
    """A benchmark source violated its immutable download contract."""


_SHA256 = re.compile(r"[0-9a-f]{64}")


def fetch_hash_pinned_file(
    *,
    artifact_id: str,
    source_url: str,
    content_sha256: str,
    expected_bytes: int | None,
    max_bytes: int,
    cache_dir: Path,
    suffix: str,
    offline: bool,
    attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> Path:
    """Fetch one immutable artifact without ever accepting unverified bytes."""
    if not artifact_id.strip():
        raise EvaluationDownloadError("evaluation artifact ID must be non-empty")
    if not source_url.startswith("https://"):
        raise EvaluationDownloadError(f"{artifact_id}: source URL must use HTTPS")
    if _SHA256.fullmatch(content_sha256) is None:
        raise EvaluationDownloadError(f"{artifact_id}: expected hash must be lowercase SHA-256")
    if expected_bytes is not None and (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 1
    ):
        raise EvaluationDownloadError(f"{artifact_id}: expected size must be a positive integer")
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes < 1
        or (expected_bytes is not None and max_bytes < expected_bytes)
    ):
        raise EvaluationDownloadError(f"{artifact_id}: artifact size limit is invalid")
    if not suffix.startswith(".") or any(character in suffix for character in "/\\"):
        raise EvaluationDownloadError(f"{artifact_id}: cache suffix is invalid")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 5:
        raise EvaluationDownloadError(f"{artifact_id}: download attempts must be within 1..=5")
    if (
        not isinstance(retry_delay_seconds, (int, float))
        or isinstance(retry_delay_seconds, bool)
        or not math.isfinite(retry_delay_seconds)
        or not 0 <= retry_delay_seconds <= 60
    ):
        raise EvaluationDownloadError(
            f"{artifact_id}: retry delay must be finite and within 0..=60 seconds"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{content_sha256}{suffix}"
    if path.is_file():
        actual_bytes = path.stat().st_size
        if actual_bytes > max_bytes:
            raise EvaluationDownloadError(f"{artifact_id}: cached artifact exceeds size limit")
        if expected_bytes is not None and actual_bytes != expected_bytes:
            raise EvaluationDownloadError(
                f"{artifact_id}: cached size mismatch; expected {expected_bytes}, got {actual_bytes}"
            )
        with path.open("rb") as source:
            cached_digest = hashlib.file_digest(source, "sha256").hexdigest()
        if cached_digest != content_sha256:
            raise EvaluationDownloadError(
                f"{artifact_id}: cached SHA-256 mismatch; expected {content_sha256}, got {cached_digest}"
            )
        return path
    if offline:
        raise EvaluationDownloadError(f"{artifact_id}: artifact is not cached in offline mode")
    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "Tokito-DSViRe-Evaluation/1.0"},
    )
    for attempt in range(1, attempts + 1):
        temporary: Path | None = None
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.geturl().startswith("https://"):
                    raise EvaluationDownloadError(
                        f"{artifact_id}: download redirected away from HTTPS"
                    )
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        declared_bytes = int(declared)
                    except ValueError as exc:
                        raise EvaluationDownloadError(
                            f"{artifact_id}: invalid download content-length"
                        ) from exc
                    if declared_bytes < 0 or declared_bytes > max_bytes:
                        raise EvaluationDownloadError(
                            f"{artifact_id}: declared download size exceeds limit"
                        )
                    if expected_bytes is not None and declared_bytes != expected_bytes:
                        raise EvaluationDownloadError(
                            f"{artifact_id}: declared size mismatch; "
                            f"expected {expected_bytes}, got {declared_bytes}"
                        )
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{content_sha256}.",
                    suffix=".tmp",
                    dir=cache_dir,
                    delete=False,
                ) as target:
                    temporary = Path(target.name)
                    download_digest = hashlib.sha256()
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes or (
                            expected_bytes is not None and total > expected_bytes
                        ):
                            raise EvaluationDownloadError(
                                f"{artifact_id}: download exceeds expected size"
                            )
                        download_digest.update(chunk)
                        target.write(chunk)
            if expected_bytes is not None and total != expected_bytes:
                raise EvaluationDownloadError(
                    f"{artifact_id}: downloaded size mismatch; expected {expected_bytes}, got {total}"
                )
            actual_digest = download_digest.hexdigest()
            if actual_digest == content_sha256:
                assert temporary is not None
                temporary.replace(path)
                return path
            if attempt == attempts:
                raise EvaluationDownloadError(
                    f"{artifact_id}: downloaded SHA-256 mismatch after {attempts} attempts; "
                    f"expected {content_sha256}, got {actual_digest}"
                )
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        time.sleep(retry_delay_seconds * attempt)
    raise AssertionError("bounded download loop exited without a result")


def fetch_hash_pinned_pdf(
    *,
    case_id: str,
    source_url: str,
    content_sha256: str,
    cache_dir: Path,
    offline: bool,
    attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> bytes:
    path = fetch_hash_pinned_file(
        artifact_id=case_id,
        source_url=source_url,
        content_sha256=content_sha256,
        expected_bytes=None,
        max_bytes=MAX_PDF_BYTES,
        cache_dir=cache_dir,
        suffix=".pdf",
        offline=offline,
        attempts=attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    return path.read_bytes()

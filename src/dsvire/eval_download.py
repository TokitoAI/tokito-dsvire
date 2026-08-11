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
    if not case_id.strip():
        raise EvaluationDownloadError("evaluation case ID must be non-empty")
    if not source_url.startswith("https://"):
        raise EvaluationDownloadError(f"{case_id}: source URL must use HTTPS")
    if _SHA256.fullmatch(content_sha256) is None:
        raise EvaluationDownloadError(f"{case_id}: expected hash must be lowercase SHA-256")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 5:
        raise EvaluationDownloadError(f"{case_id}: download attempts must be within 1..=5")
    if (
        not isinstance(retry_delay_seconds, (int, float))
        or isinstance(retry_delay_seconds, bool)
        or not math.isfinite(retry_delay_seconds)
        or not 0 <= retry_delay_seconds <= 60
    ):
        raise EvaluationDownloadError(
            f"{case_id}: retry delay must be finite and within 0..=60 seconds"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{content_sha256}.pdf"
    if path.is_file():
        if path.stat().st_size > MAX_PDF_BYTES:
            raise EvaluationDownloadError(f"{case_id}: cached PDF exceeds size limit")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != content_sha256:
            raise EvaluationDownloadError(
                f"{case_id}: cached SHA-256 mismatch; expected {content_sha256}, got {digest}"
            )
        return payload
    if offline:
        raise EvaluationDownloadError(f"{case_id}: PDF is not cached in offline mode")
    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "Tokito-DSViRe-Evaluation/1.0"},
    )
    for attempt in range(1, attempts + 1):
        temporary: Path | None = None
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.geturl().startswith("https://"):
                    raise EvaluationDownloadError(f"{case_id}: download redirected away from HTTPS")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        declared_bytes = int(declared)
                    except ValueError as exc:
                        raise EvaluationDownloadError(
                            f"{case_id}: invalid download content-length"
                        ) from exc
                    if declared_bytes < 0 or declared_bytes > MAX_PDF_BYTES:
                        raise EvaluationDownloadError(
                            f"{case_id}: declared download size exceeds PDF limit"
                        )
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{content_sha256}.",
                    suffix=".tmp",
                    dir=cache_dir,
                    delete=False,
                ) as target:
                    temporary = Path(target.name)
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_PDF_BYTES:
                            raise EvaluationDownloadError(
                                f"{case_id}: download exceeds PDF size limit"
                            )
                        target.write(chunk)
            assert temporary is not None
            payload = temporary.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest == content_sha256:
                temporary.replace(path)
                return payload
            if attempt == attempts:
                raise EvaluationDownloadError(
                    f"{case_id}: downloaded SHA-256 mismatch after {attempts} attempts; "
                    f"expected {content_sha256}, got {digest}"
                )
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        time.sleep(retry_delay_seconds * attempt)
    raise AssertionError("bounded download loop exited without a result")

"""Bounded, hash-pinned downloader shared by evaluation commands."""

from __future__ import annotations

import hashlib
import re
import tempfile
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
) -> bytes:
    if not case_id.strip():
        raise EvaluationDownloadError("evaluation case ID must be non-empty")
    if not source_url.startswith("https://"):
        raise EvaluationDownloadError(f"{case_id}: source URL must use HTTPS")
    if _SHA256.fullmatch(content_sha256) is None:
        raise EvaluationDownloadError(f"{case_id}: expected hash must be lowercase SHA-256")
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
                        raise EvaluationDownloadError(f"{case_id}: download exceeds PDF size limit")
                    target.write(chunk)
        assert temporary is not None
        payload = temporary.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != content_sha256:
            raise EvaluationDownloadError(
                f"{case_id}: downloaded SHA-256 mismatch; expected {content_sha256}, got {digest}"
            )
        temporary.replace(path)
        return payload
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

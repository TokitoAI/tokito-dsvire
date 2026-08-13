"""Exact-source resolution shared by source-free evaluation runners."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .eval_download import fetch_hash_pinned_file
from .pipeline import MAX_PDF_BYTES


def resolve_registered_sources(
    cache_roots: Sequence[Path],
    documents: Sequence[Any],
    download_cache: Path | None,
    offline: bool,
) -> dict[str, Path]:
    """Resolve every document by content hash; URLs never override identity."""
    expected = {document.content_sha256: document.document_id for document in documents}
    found: dict[str, Path] = {}
    for root in cache_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.pdf"):
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest in expected:
                found.setdefault(digest, path)
    for document in documents:
        if document.content_sha256 in found:
            continue
        if download_cache is None:
            raise ValueError(
                f"missing exact registered source {document.document_id}; set --download-cache"
            )
        source_url = getattr(document.source, "url", None)
        if not isinstance(source_url, str) or not source_url:
            raise ValueError(f"{document.document_id}: source URL is invalid")
        found[document.content_sha256] = fetch_hash_pinned_file(
            artifact_id=document.document_id,
            source_url=source_url,
            content_sha256=document.content_sha256,
            expected_bytes=None,
            max_bytes=MAX_PDF_BYTES,
            cache_dir=download_cache,
            suffix=".pdf",
            offline=offline,
        )
    return found

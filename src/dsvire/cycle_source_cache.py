"""Materialize sealed cycle PDFs into a private cache. Bytes are never committed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .eval_download import fetch_hash_pinned_file
from .pipeline import MAX_PDF_BYTES
from .retrieval_source_seal import SourceSealError, validate_source_manifest


def materialize_sealed_cycle_pdfs(
    manifest: Mapping[str, Any],
    cache_dir: Path,
    *,
    expected_family_ids: set[str],
    offline: bool = False,
) -> tuple[Path, ...]:
    """Download each sealed official PDF by hash. Does not rewrite the manifest."""
    validate_source_manifest(manifest, expected_family_ids=expected_family_ids)
    if manifest.get("complete") is not True or manifest.get("invalidations") != []:
        raise SourceSealError("sealed source manifest is incomplete or invalidated")
    paths: list[Path] = []
    for source in manifest["sources"]:
        if not isinstance(source, Mapping):
            raise SourceSealError("sealed source record is invalid")
        url = source.get("requested_url")
        if not isinstance(url, str) or not url:
            raise SourceSealError(f"{source.get('id')}: requested URL is missing")
        size = source["bytes"]
        if not isinstance(size, int) or isinstance(size, bool):
            raise SourceSealError(f"{source['id']}: source size is invalid")
        paths.append(
            fetch_hash_pinned_file(
                artifact_id=str(source["id"]),
                source_url=url,
                content_sha256=str(source["content_sha256"]),
                expected_bytes=size,
                max_bytes=MAX_PDF_BYTES,
                cache_dir=cache_dir,
                suffix=".pdf",
                offline=offline,
            )
        )
    return tuple(paths)


def family_ids_from_plan(plan: Mapping[str, Any]) -> set[str]:
    families = plan.get("families")
    if not isinstance(families, Sequence) or isinstance(families, (str, bytes)):
        raise SourceSealError("plan families must be an array")
    ids = {str(family["id"]) for family in families if isinstance(family, Mapping)}
    if len(ids) != len(families):
        raise SourceSealError("plan families are invalid")
    return ids

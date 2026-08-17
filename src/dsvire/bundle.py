"""Deterministic, self-verifying DS-ViRe result bundles."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass

_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class Bundle:
    payload: bytes
    sha256: str
    manifest: dict[str, object]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def build_bundle(files: Mapping[str, bytes], metadata: Mapping[str, object]) -> Bundle:
    """Create a byte-for-byte reproducible ZIP with a hash manifest."""
    if not files:
        raise ValueError("bundle must contain at least one artifact")
    clean: dict[str, bytes] = {}
    for name, payload in files.items():
        normalized = name.replace("\\", "/").lstrip("/")
        if not normalized or normalized.startswith("../") or "/../" in normalized:
            raise ValueError(f"unsafe bundle path: {name!r}")
        if normalized == "manifest.json" or normalized in clean:
            raise ValueError(f"reserved or duplicate bundle path: {normalized!r}")
        clean[normalized] = payload
    manifest: dict[str, object] = {
        "schema_version": "dsvire.bundle.v1",
        "metadata": dict(metadata),
        "files": [
            {
                "path": name,
                "bytes": len(clean[name]),
                "sha256": hashlib.sha256(clean[name]).hexdigest(),
            }
            for name in sorted(clean)
        ],
    }
    entries = clean | {"manifest.json": _canonical(manifest)}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, _ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])
    payload = output.getvalue()
    return Bundle(payload, hashlib.sha256(payload).hexdigest(), manifest)

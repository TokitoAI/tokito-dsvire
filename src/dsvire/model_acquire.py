"""Stream and verify manifest-pinned model files without importing an ML runtime."""

from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .model_manifest import (
    ModelFile,
    ModelManifestError,
    ModelRepository,
    load_model_manifest,
    materialize_offline_model,
    verify_snapshot,
)

MAX_REDIRECTS = 8
CHUNK_BYTES = 1024 * 1024
OpenUrl = Callable[[urllib.request.Request, int], Any]


class NoUnsafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        redirects = getattr(req, "redirect_dict", {})
        if len(redirects) >= MAX_REDIRECTS:
            raise ModelManifestError("model download exceeded redirect limit")
        if not newurl.startswith("https://"):
            raise ModelManifestError("model download redirected outside HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_model_file(
    repository: ModelRepository,
    file: ModelFile,
    destination: Path,
    *,
    open_url: OpenUrl | None = None,
) -> None:
    quoted = urllib.parse.quote(file.path, safe="")
    url = f"https://huggingface.co/{repository.repository}/resolve/{repository.revision}/{quoted}"
    request = urllib.request.Request(url, headers={"User-Agent": "tokito-dsvire-model-acquire/1"})
    digest = hashlib.sha256()
    written = 0
    client = urllib.request.build_opener(NoUnsafeRedirect())
    opener = open_url or (lambda value, timeout: client.open(value, timeout=timeout))
    try:
        with opener(request, 60) as response, destination.open("xb") as output:
            while chunk := response.read(CHUNK_BYTES):
                written += len(chunk)
                if written > file.bytes:
                    raise ModelManifestError(f"{repository.name}/{file.path} exceeds expected size")
                digest.update(chunk)
                output.write(chunk)
    except (OSError, urllib.error.URLError):
        destination.unlink(missing_ok=True)
        raise ModelManifestError(f"failed to download {repository.name}/{file.path}") from None
    except ModelManifestError:
        destination.unlink(missing_ok=True)
        raise
    if written != file.bytes or digest.hexdigest() != file.sha256:
        destination.unlink(missing_ok=True)
        raise ModelManifestError(f"{repository.name}/{file.path} size or digest mismatch")


def acquire_model(manifest_path: Path, destination: Path) -> Path:
    manifest = load_model_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    if destination.exists():
        raise ModelManifestError("model destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-download-", dir=destination.parent
    ) as temp:
        download_root = Path(temp)
        snapshots: dict[str, Path] = {}
        for repository in manifest.repositories:
            root = download_root / repository.name
            root.mkdir()
            snapshots[repository.name] = root
            for file in repository.files:
                download_model_file(repository, file, root / file.path)
            verify_snapshot(repository, root)
        return materialize_offline_model(manifest, snapshots, destination)

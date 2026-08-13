"""Strict model-file manifests and offline materialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_VERSION = "dsvire.model-manifest.v1"
SHA256 = re.compile(r"[0-9a-f]{64}")
REVISION = re.compile(r"[0-9a-f]{40}")
MAX_FILES = 256
MAX_TOTAL_BYTES = 20_000_000_000


class ModelManifestError(ValueError):
    """A model manifest or snapshot violates its immutable-file contract."""


@dataclass(frozen=True)
class ModelFile:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class ModelRepository:
    name: str
    repository: str
    revision: str
    license: str
    files: tuple[ModelFile, ...]


@dataclass(frozen=True)
class ModelManifest:
    id: str
    license: str
    repositories: tuple[ModelRepository, ...]
    runtime: Mapping[str, Any]
    content_sha256: str


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def verify_materialized_adapter_config(manifest: ModelManifest, model_root: Path) -> None:
    """Verify the rewritten adapter config after normalizing its local base pointer."""
    repositories = {repository.name: repository for repository in manifest.repositories}
    expected = manifest.runtime.get("adapter_config_semantic_sha256")
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        raise ModelManifestError("adapter config semantic digest is invalid")
    path = model_root / "adapter" / "adapter_config.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        raise ModelManifestError("materialized adapter config is unsafe")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelManifestError("materialized adapter config is invalid") from exc
    if not isinstance(config, dict):
        raise ModelManifestError("materialized adapter config must be an object")
    expected_base = os.fspath((model_root / "base").resolve())
    if config.get("base_model_name_or_path") != expected_base or config.get("revision") is not None:
        raise ModelManifestError("materialized adapter config has an invalid local base binding")
    config["base_model_name_or_path"] = repositories["base"].repository
    if hashlib.sha256(_canonical(config)).hexdigest() != expected:
        raise ModelManifestError("materialized adapter config semantic digest mismatch")


def _text(value: Any, context: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > maximum or "\x00" in value:
        raise ModelManifestError(f"{context} must be bounded non-empty text")
    return value


def _safe_path(value: Any, context: str) -> str:
    path = _text(value, context, maximum=1024)
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or len(parsed.parts) != 1 or parsed.parts[0] in {".", ".."}:
        raise ModelManifestError(f"{context} must be a safe root-level filename")
    return path


def load_model_manifest(value: Any) -> ModelManifest:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "id",
        "license",
        "repositories",
        "runtime",
    }:
        raise ModelManifestError("model manifest keys are invalid")
    if value["schema_version"] != MANIFEST_VERSION:
        raise ModelManifestError("unsupported model manifest version")
    raw_repositories = value["repositories"]
    if not isinstance(raw_repositories, list) or not 1 <= len(raw_repositories) <= 8:
        raise ModelManifestError("repositories are outside their count limit")
    repositories: list[ModelRepository] = []
    names: set[str] = set()
    total_files = total_bytes = 0
    for repository_index, raw in enumerate(raw_repositories):
        context = f"repositories[{repository_index}]"
        if not isinstance(raw, Mapping) or set(raw) != {
            "name",
            "repository",
            "revision",
            "license",
            "files",
        }:
            raise ModelManifestError(f"{context} keys are invalid")
        name = _text(raw["name"], f"{context}.name", maximum=64)
        if name in names or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ModelManifestError(f"{context}.name is invalid or duplicate")
        names.add(name)
        revision = _text(raw["revision"], f"{context}.revision", maximum=40)
        if REVISION.fullmatch(revision) is None:
            raise ModelManifestError(f"{context}.revision must be a full lowercase commit")
        raw_files = raw["files"]
        if not isinstance(raw_files, list) or not raw_files:
            raise ModelManifestError(f"{context}.files must be non-empty")
        files: list[ModelFile] = []
        paths: set[str] = set()
        for file_index, file in enumerate(raw_files):
            file_context = f"{context}.files[{file_index}]"
            if not isinstance(file, Mapping) or set(file) != {"path", "bytes", "sha256"}:
                raise ModelManifestError(f"{file_context} keys are invalid")
            path = _safe_path(file["path"], f"{file_context}.path")
            size = file["bytes"]
            digest = file["sha256"]
            if path in paths:
                raise ModelManifestError(f"{context}.files contain duplicate paths")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not 1 <= size <= MAX_TOTAL_BYTES
            ):
                raise ModelManifestError(f"{file_context}.bytes is invalid")
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise ModelManifestError(f"{file_context}.sha256 is invalid")
            paths.add(path)
            total_files += 1
            total_bytes += size
            files.append(ModelFile(path, size, digest))
        if [file.path for file in files] != sorted(paths):
            raise ModelManifestError(f"{context}.files must be sorted by path")
        repositories.append(
            ModelRepository(
                name,
                _text(raw["repository"], f"{context}.repository"),
                revision,
                _text(raw["license"], f"{context}.license"),
                tuple(files),
            )
        )
    if total_files > MAX_FILES or total_bytes > MAX_TOTAL_BYTES:
        raise ModelManifestError("model manifest exceeds its aggregate file limit")
    if [repo.name for repo in repositories] != sorted(names):
        raise ModelManifestError("repositories must be sorted by name")
    runtime = value["runtime"]
    if not isinstance(runtime, Mapping) or not runtime:
        raise ModelManifestError("runtime must be a non-empty object")
    return ModelManifest(
        _text(value["id"], "id"),
        _text(value["license"], "license"),
        tuple(repositories),
        dict(runtime),
        hashlib.sha256(_canonical(value)).hexdigest(),
    )


def verify_snapshot(
    repository: ModelRepository, root: Path, *, ignored_files: frozenset[str] = frozenset()
) -> None:
    if not root.is_dir():
        raise ModelManifestError(f"{repository.name} snapshot directory is missing")
    expected = {file.path for file in repository.files}
    for name in ignored_files:
        path = root / _safe_path(name, "ignored_files")
        if path.is_symlink() or not path.is_file():
            raise ModelManifestError(f"{repository.name}/{name} ignored file is unsafe")
    actual = {path.name for path in root.iterdir() if path.is_file()} - ignored_files
    if actual != expected:
        raise ModelManifestError(f"{repository.name} snapshot file set mismatch")
    for file in repository.files:
        path = root / file.path
        if path.is_symlink() or not path.is_file() or path.stat().st_size != file.bytes:
            raise ModelManifestError(f"{repository.name}/{file.path} size or type mismatch")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != file.sha256:
            raise ModelManifestError(f"{repository.name}/{file.path} digest mismatch")


def materialize_offline_model(
    manifest: ModelManifest, snapshots: Mapping[str, Path], destination: Path
) -> Path:
    """Atomically copy verified files and bind the adapter to the verified local base."""
    if set(snapshots) != {repository.name for repository in manifest.repositories}:
        raise ModelManifestError("snapshot names differ from model manifest")
    if destination.exists():
        raise ModelManifestError("offline model destination already exists")
    repositories = {repository.name: repository for repository in manifest.repositories}
    if set(repositories) != {"adapter", "base"}:
        raise ModelManifestError("offline ColSmol materialization requires adapter and base")
    for name, repository in repositories.items():
        verify_snapshot(repository, snapshots[name])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-", dir=destination.parent
    ) as temp:
        staging = Path(temp)
        for name, repository in repositories.items():
            target = staging / name
            target.mkdir()
            for file in repository.files:
                shutil.copyfile(snapshots[name] / file.path, target / file.path)
        adapter_config = staging / "adapter" / "adapter_config.json"
        try:
            config = json.loads(adapter_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelManifestError("adapter_config.json is invalid") from exc
        if config.get("base_model_name_or_path") != repositories["base"].repository:
            raise ModelManifestError("adapter base model pointer differs from manifest")
        config["base_model_name_or_path"] = os.fspath((destination / "base").resolve())
        config["revision"] = None
        adapter_config.write_bytes(_canonical(config))
        os.replace(staging, destination)
    verify_materialized_adapter_config(manifest, destination)
    return destination / "adapter"

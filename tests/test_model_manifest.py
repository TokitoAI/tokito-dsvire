from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from dsvire.model_manifest import (
    ModelManifest,
    ModelManifestError,
    load_model_manifest,
    materialize_offline_model,
    verify_snapshot,
)

ROOT = Path(__file__).parents[1]


def _file(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _manifest(adapter_config: bytes, adapter: bytes, base: bytes) -> dict[str, Any]:
    semantic_config = json.loads(adapter_config)
    semantic_config["revision"] = None
    semantic_digest = hashlib.sha256(
        json.dumps(
            semantic_config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    return {
        "schema_version": "dsvire.model-manifest.v1",
        "id": "test/model@" + "1" * 40,
        "license": "MIT",
        "repositories": [
            {
                "name": "adapter",
                "repository": "test/adapter",
                "revision": "1" * 40,
                "license": "MIT",
                "files": sorted(
                    [_file("adapter_config.json", adapter_config), _file("weights.bin", adapter)],
                    key=lambda item: item["path"],
                ),
            },
            {
                "name": "base",
                "repository": "test/base",
                "revision": "2" * 40,
                "license": "MIT",
                "files": [_file("model.bin", base)],
            },
        ],
        "runtime": {
            "engine": "1.0.0",
            "adapter_config_semantic_sha256": semantic_digest,
        },
    }


def _snapshots(tmp_path: Path) -> tuple[ModelManifest, dict[str, Path]]:
    config = json.dumps({"base_model_name_or_path": "test/base"}).encode()
    adapter, base = b"adapter", b"base"
    roots = {"adapter": tmp_path / "source-adapter", "base": tmp_path / "source-base"}
    for root in roots.values():
        root.mkdir()
    (roots["adapter"] / "adapter_config.json").write_bytes(config)
    (roots["adapter"] / "weights.bin").write_bytes(adapter)
    (roots["base"] / "model.bin").write_bytes(base)
    return load_model_manifest(_manifest(config, adapter, base)), roots


def test_committed_colsmol_manifest_is_valid_and_binds_expected_weights() -> None:
    raw = json.loads((ROOT / "evaluation/models/colsmol-256m.v1.json").read_text())
    schema = json.loads((ROOT / "scripts/schema/model_manifest_v1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    manifest = load_model_manifest(raw)
    files = {repo.name: {file.path: file for file in repo.files} for repo in manifest.repositories}
    assert (
        files["adapter"]["adapter_model.safetensors"].sha256
        == "41673fb85f448ff15356e4dfcf9e039d7c6e3cffa1936bc3513f55453005e63e"
    )
    assert (
        files["base"]["model.safetensors"].sha256
        == "45d026bad7c9d27edaeaf8ba4f2f0cd28406179819e06fa52693c051838c9069"
    )
    assert manifest.runtime["embedding_dimension"] == 128


def test_verify_and_atomically_materialize_offline_model(tmp_path: Path) -> None:
    manifest, roots = _snapshots(tmp_path)
    destination = tmp_path / "offline"
    adapter = materialize_offline_model(manifest, roots, destination)
    config = json.loads((adapter / "adapter_config.json").read_text())
    assert config["base_model_name_or_path"] == str((destination / "base").resolve())
    assert config["revision"] is None
    assert (destination / "base/model.bin").read_bytes() == b"base"
    with pytest.raises(ModelManifestError, match="already exists"):
        materialize_offline_model(manifest, roots, destination)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("missing", "file set mismatch"),
        ("extra", "file set mismatch"),
        ("size", "size or type mismatch"),
        ("digest", "digest mismatch"),
    ],
)
def test_snapshot_fails_closed(tmp_path: Path, mutation: str, message: str) -> None:
    manifest, roots = _snapshots(tmp_path)
    repository = manifest.repositories[0]
    if mutation == "missing":
        (roots["adapter"] / "weights.bin").unlink()
    elif mutation == "extra":
        (roots["adapter"] / "extra.bin").write_bytes(b"x")
    elif mutation == "size":
        (roots["adapter"] / "weights.bin").write_bytes(b"longer")
    elif mutation == "digest":
        (roots["adapter"] / "weights.bin").write_bytes(b"changed")
    with pytest.raises(ModelManifestError, match=message):
        verify_snapshot(repository, roots["adapter"])


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("traversal", "safe root-level"),
        ("duplicate_repo", "invalid or duplicate"),
        ("short_revision", "full lowercase commit"),
        ("unsorted", "sorted by path"),
        ("unknown", "keys are invalid"),
    ],
)
def test_manifest_fails_closed(mutation: str, message: str) -> None:
    config = json.dumps({"base_model_name_or_path": "test/base"}).encode()
    raw = _manifest(config, b"adapter", b"base")
    broken = deepcopy(raw)
    if mutation == "traversal":
        broken["repositories"][0]["files"][0]["path"] = "../secret"
    elif mutation == "duplicate_repo":
        broken["repositories"][1]["name"] = "adapter"
    elif mutation == "short_revision":
        broken["repositories"][0]["revision"] = "abc"
    elif mutation == "unsorted":
        broken["repositories"][0]["files"].reverse()
    elif mutation == "unknown":
        broken["repositories"][0]["branch"] = "main"
    with pytest.raises(ModelManifestError, match=message):
        load_model_manifest(broken)


def test_materialization_rejects_wrong_base_pointer(tmp_path: Path) -> None:
    manifest, roots = _snapshots(tmp_path)
    config = b'{"base_model_name_or_path":"untrusted/base"}'
    (roots["adapter"] / "adapter_config.json").write_bytes(config)
    raw = _manifest(config, b"adapter", b"base")
    manifest = load_model_manifest(raw)
    with pytest.raises(ModelManifestError, match="base model pointer"):
        materialize_offline_model(manifest, roots, tmp_path / "offline")


def test_materialized_adapter_config_rejects_semantic_tampering(tmp_path: Path) -> None:
    manifest, roots = _snapshots(tmp_path)
    destination = tmp_path / "offline"
    materialize_offline_model(manifest, roots, destination)
    config_path = destination / "adapter" / "adapter_config.json"
    config = json.loads(config_path.read_text())
    config["r"] = 999
    config_path.write_text(json.dumps(config))
    from dsvire.model_manifest import verify_materialized_adapter_config

    with pytest.raises(ModelManifestError, match="semantic digest mismatch"):
        verify_materialized_adapter_config(manifest, destination)

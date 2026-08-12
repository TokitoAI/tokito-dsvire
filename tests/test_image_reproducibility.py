from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "compare_image_rootfs.py"
    spec = importlib.util.spec_from_file_location("dsvire_compare_image_rootfs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rootfs(
    path: Path, files: dict[str, bytes], *, reverse: bool = False, mode: int = 0o640
) -> None:
    items = list(files.items())
    if reverse:
        items.reverse()
    with tarfile.open(path, "w") as archive:
        for name, content in items:
            member = tarfile.TarInfo(name)
            member.mode = mode
            member.uid = 10001
            member.gid = 10001
            member.mtime = 123 if not reverse else 999
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def _compare(first: Path, second: Path) -> dict[str, object]:
    return _module().compare(
        first,
        second,
        source_commit="a" * 40,
        base_image="python@example",
        first_image_id="sha256:first",
        second_image_id="sha256:second",
    )


def test_rootfs_digest_ignores_tar_order_mtime_and_runtime_injections(tmp_path: Path) -> None:
    first, second = tmp_path / "first.tar", tmp_path / "second.tar"
    application = {"app/code.py": b"safe", "etc/hosts": b"container-one"}
    _rootfs(first, application)
    application["etc/hosts"] = b"container-two"
    _rootfs(second, application, reverse=True)
    report = _compare(first, second)
    assert report["ok"] is True
    assert report["differing_paths"] == []
    assert report["first"]["rootfs_digest"] == report["second"]["rootfs_digest"]  # type: ignore[index]


def test_rootfs_digest_detects_content_drift_and_names_path(tmp_path: Path) -> None:
    first, second = tmp_path / "first.tar", tmp_path / "second.tar"
    _rootfs(first, {"app/code.py": b"first"})
    _rootfs(second, {"app/code.py": b"second"})
    report = _compare(first, second)
    assert report["ok"] is False
    assert report["differing_paths"] == ["app/code.py"]


def test_rootfs_digest_detects_permission_drift(tmp_path: Path) -> None:
    first, second = tmp_path / "first.tar", tmp_path / "second.tar"
    _rootfs(first, {"app/code.py": b"same"})
    _rootfs(second, {"app/code.py": b"same"}, mode=0o777)
    report = _compare(first, second)
    assert report["ok"] is False
    assert report["differing_paths"] == ["app/code.py"]

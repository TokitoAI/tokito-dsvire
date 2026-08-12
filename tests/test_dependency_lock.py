from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _checker() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "check_dependency_lock.py"
    spec = importlib.util.spec_from_file_location("dsvire_check_dependency_lock", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_lock_comparison_is_newline_independent(tmp_path: Path) -> None:
    lf = tmp_path / "lf.lock"
    crlf = tmp_path / "crlf.lock"
    content = "package==1.0 \\\n    --hash=sha256:abc\n"
    lf.write_bytes(content.encode())
    crlf.write_bytes(content.replace("\n", "\r\n").encode())
    assert _checker().locks_equal(lf, crlf)


def test_runtime_lock_comparison_still_detects_dependency_drift(tmp_path: Path) -> None:
    first = tmp_path / "first.lock"
    second = tmp_path / "second.lock"
    first.write_text("package==1.0\n", encoding="utf-8")
    second.write_text("package==1.1\n", encoding="utf-8")
    assert not _checker().locks_equal(first, second)

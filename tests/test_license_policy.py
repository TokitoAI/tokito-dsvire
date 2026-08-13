from __future__ import annotations

import datetime as dt
import json
import platform
import sys
from pathlib import Path

import pytest

from dsvire.license_policy import (
    DEFAULT_NOTICES,
    DEFAULT_POLICY,
    LicensePolicyError,
    active_lock_inventory,
    audit,
    load_policy,
    lock_inventory,
    notices,
)


def test_active_inventory_applies_audited_platform_markers() -> None:
    active = active_lock_inventory()
    assert ("colorama" in active) is (sys.platform == "win32")
    assert ("uvloop" in active) is (
        platform.python_implementation() != "PyPy" and sys.platform not in {"cygwin", "win32"}
    )


def test_unknown_lock_marker_fails_closed(tmp_path: Path) -> None:
    lock = tmp_path / "runtime.lock"
    lock.write_text("example==1.0 ; python_version > '3.10' \\\n", encoding="utf-8")
    with pytest.raises(LicensePolicyError, match="unsupported runtime lock marker"):
        active_lock_inventory(lock)


def test_exact_runtime_inventory_is_fully_dispositioned() -> None:
    locked = lock_inventory()
    policy = load_policy(today=dt.date(2026, 8, 12))
    assert set(locked) == {package.name for package in policy.packages}
    assert len(locked) == 24
    report = audit(today=dt.date(2026, 8, 12))
    assert report["ok"] is True
    assert report["release_ready"] is True
    assert report["legal_decisions"] == []
    evidence = report["license_evidence"]["pypdfium2"]
    assert {item["path"] for item in evidence} == {
        "licenses/LICENSES/Apache-2.0.txt",
        "licenses/LICENSES/BSD-3-Clause.txt",
        "BUILD_LICENSES/pdfium.txt",
    }
    assert all(len(item["sha256"]) == 64 for item in evidence)


def test_generated_notices_are_current_and_surface_redistribution_obligations() -> None:
    expected = notices()
    assert DEFAULT_NOTICES.read_text(encoding="utf-8") == expected
    assert "requires_legal_decision" not in expected
    assert "Redistribution obligations" in expected
    assert "bundled native dependency license texts" in expected


def test_missing_required_license_payload_fails_closed(tmp_path: Path) -> None:
    data = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    package = next(item for item in data["packages"] if item["name"] == "pypdfium2")
    package["required_license_files"].append("licenses/DOES_NOT_EXIST")
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LicensePolicyError, match="required bundled license file missing"):
        audit(policy_path=path, today=dt.date(2026, 8, 13))


def test_new_locked_dependency_without_policy_fails_closed(tmp_path: Path) -> None:
    lock = tmp_path / "runtime.lock"
    lock.write_text(
        (Path(__file__).parents[1] / "requirements/runtime.lock").read_text(encoding="utf-8")
        + "new-package==1.0 \\\n    --hash=sha256:"
        + "a" * 64
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LicensePolicyError, match="policy/lock drift"):
        audit(lock_path=lock, today=dt.date(2026, 8, 12))


def test_allowed_status_cannot_bypass_allowlist(tmp_path: Path) -> None:
    data = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    data["packages"][0]["license"] = "GPL-3.0-only"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(LicensePolicyError, match="is not allowed"):
        load_policy(path, today=dt.date(2026, 8, 12))

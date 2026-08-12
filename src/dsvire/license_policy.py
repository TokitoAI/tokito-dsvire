"""Fail-closed exact-runtime license inventory and release disposition."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import platform
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, cast

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "policy" / "runtime-licenses.v1.json"
DEFAULT_LOCK = ROOT / "requirements" / "runtime.lock"
DEFAULT_NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
SCHEMA = "dsvire.runtime-license-policy.v1"
LOCK_ENTRY = re.compile(r"^([a-z0-9][a-z0-9._-]*)==([^ ;\\]+)(?:\s*;\s*([^\\]+))?")
Status = Literal["allowed", "requires_legal_decision"]


class LicensePolicyError(RuntimeError):
    """The runtime inventory or its policy is incomplete, stale, or forbidden."""


@dataclasses.dataclass(frozen=True)
class PackagePolicy:
    name: str
    version: str
    license: str
    status: Status
    exception_expires: str | None = None
    owner: str | None = None
    evidence: str | None = None
    obligations: str | None = None


@dataclasses.dataclass(frozen=True)
class Policy:
    reviewed_at: str
    allowed: frozenset[str]
    packages: tuple[PackagePolicy, ...]


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def lock_inventory(path: Path = DEFAULT_LOCK) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCK_ENTRY.match(line)
        if match is None:
            continue
        name, version = canonical_name(match.group(1)), match.group(2)
        if name in inventory:
            raise LicensePolicyError(f"duplicate runtime lock package: {name}")
        inventory[name] = version
    if not inventory:
        raise LicensePolicyError("runtime lock inventory is empty")
    return inventory


def active_lock_inventory(path: Path = DEFAULT_LOCK) -> dict[str, str]:
    """Return packages selected by the lock's audited platform markers."""
    inventory: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCK_ENTRY.match(line)
        if match is None:
            continue
        name, version = canonical_name(match.group(1)), match.group(2)
        marker = (match.group(3) or "").strip()
        active = True
        if marker == "sys_platform == 'win32'":
            active = sys.platform == "win32"
        elif marker == (
            "platform_python_implementation != 'PyPy' and sys_platform != 'cygwin' "
            "and sys_platform != 'win32'"
        ):
            active = platform.python_implementation() != "PyPy" and sys.platform not in {
                "cygwin",
                "win32",
            }
        elif marker:
            raise LicensePolicyError(f"unsupported runtime lock marker for {name}: {marker}")
        if active:
            if name in inventory:
                raise LicensePolicyError(f"duplicate active runtime lock package: {name}")
            inventory[name] = version
    if not inventory:
        raise LicensePolicyError("active runtime lock inventory is empty")
    return inventory


def load_policy(path: Path = DEFAULT_POLICY, *, today: dt.date | None = None) -> Policy:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LicensePolicyError("runtime license policy is not valid JSON") from exc
    if data.get("schema_version") != SCHEMA:
        raise LicensePolicyError("unsupported runtime license policy schema")
    allowed_values = data.get("allowed_expressions")
    package_values = data.get("packages")
    if not isinstance(allowed_values, list) or not isinstance(package_values, list):
        raise LicensePolicyError("runtime license policy collections are missing")
    allowed = frozenset(str(value) for value in allowed_values)
    packages: list[PackagePolicy] = []
    seen: set[str] = set()
    now = today or dt.datetime.now(dt.UTC).date()
    for value in package_values:
        if not isinstance(value, dict):
            raise LicensePolicyError("runtime license package must be an object")
        name = canonical_name(str(value.get("name", "")))
        version = str(value.get("version", ""))
        expression = str(value.get("license", ""))
        status = str(value.get("status", ""))
        if not name or name in seen or not re.fullmatch(r"[^\s]+", version):
            raise LicensePolicyError(f"invalid or duplicate package policy: {name!r}")
        if status not in {"allowed", "requires_legal_decision"}:
            raise LicensePolicyError(f"{name}: invalid policy status")
        if status == "allowed" and expression not in allowed:
            raise LicensePolicyError(f"{name}: license {expression!r} is not allowed")
        exception_expires = value.get("exception_expires")
        owner = value.get("owner")
        evidence = value.get("evidence")
        obligations = value.get("obligations")
        if status == "requires_legal_decision":
            if not all(
                isinstance(item, str) and item
                for item in (exception_expires, owner, evidence, obligations)
            ):
                raise LicensePolicyError(f"{name}: legal-decision exception is incomplete")
            try:
                expiry = dt.date.fromisoformat(cast(str, exception_expires))
            except ValueError as exc:
                raise LicensePolicyError(f"{name}: exception expiry is invalid") from exc
            if expiry < now:
                raise LicensePolicyError(f"{name}: legal-decision exception expired on {expiry}")
        seen.add(name)
        packages.append(
            PackagePolicy(
                name,
                version,
                expression,
                cast(Status, status),
                cast(str | None, exception_expires),
                cast(str | None, owner),
                cast(str | None, evidence),
                cast(str | None, obligations),
            )
        )
    return Policy(str(data.get("reviewed_at", "")), allowed, tuple(packages))


def _metadata_license(distribution: metadata.Distribution) -> str:
    expression = distribution.metadata["License-Expression"]
    if expression:
        return str(expression).strip()
    raw = str(distribution.metadata["License"] or "").strip()
    aliases = {
        "MIT License": "MIT",
        "MIT": "MIT",
        "BSD-3-Clause": "BSD-3-Clause",
        "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License": (
            "AGPL-3.0-or-later OR LicenseRef-Artifex-Commercial"
        ),
    }
    if raw in aliases:
        return aliases[raw]
    classifiers = distribution.metadata.get_all("Classifier", [])
    if "License :: OSI Approved :: BSD License" in classifiers:
        return "BSD-3-Clause"
    if "License :: OSI Approved :: Apache Software License" in classifiers and "MIT" in raw:
        return "MIT"
    raise LicensePolicyError(
        f"{distribution.metadata['Name'] or '<unknown>'}: missing or unknown license metadata"
    )


def audit(
    policy_path: Path = DEFAULT_POLICY,
    lock_path: Path = DEFAULT_LOCK,
    *,
    today: dt.date | None = None,
) -> dict[str, Any]:
    policy = load_policy(policy_path, today=today)
    locked = lock_inventory(lock_path)
    expected = {package.name: package for package in policy.packages}
    if set(locked) != set(expected):
        missing = sorted(set(locked) - set(expected))
        stale = sorted(set(expected) - set(locked))
        raise LicensePolicyError(f"license policy/lock drift: missing={missing}, stale={stale}")
    for name, version in locked.items():
        if expected[name].version != version:
            raise LicensePolicyError(
                f"{name}: policy version {expected[name].version} != locked {version}"
            )

    installed: list[dict[str, str]] = []
    for distribution in metadata.distributions():
        raw_name = distribution.metadata["Name"]
        if not raw_name:
            continue
        name = canonical_name(raw_name)
        if name not in expected:
            continue
        package = expected[name]
        if distribution.version != package.version:
            raise LicensePolicyError(
                f"{name}: installed {distribution.version} != policy {package.version}"
            )
        observed = _metadata_license(distribution)
        if observed != package.license:
            raise LicensePolicyError(
                f"{name}: installed license {observed!r} != policy {package.license!r}"
            )
        installed.append({"name": name, "version": distribution.version, "license": observed})
    active_lock = set(active_lock_inventory(lock_path))
    if {item["name"] for item in installed} != active_lock:
        missing = sorted(active_lock - {item["name"] for item in installed})
        raise LicensePolicyError(f"locked runtime packages are not installed: {missing}")
    decisions = [
        package for package in policy.packages if package.status == "requires_legal_decision"
    ]
    return {
        "schema_version": "dsvire.runtime-license-audit.v1",
        "ok": True,
        "release_ready": not decisions,
        "runtime_package_count": len(locked),
        "installed_package_count": len(installed),
        "legal_decisions": [
            {
                "name": package.name,
                "version": package.version,
                "license": package.license,
                "exception_expires": package.exception_expires,
                "owner": package.owner,
            }
            for package in decisions
        ],
    }


def notices(policy_path: Path = DEFAULT_POLICY) -> str:
    policy = load_policy(policy_path)
    lines = [
        "# Third-party runtime notices",
        "",
        "Generated from `policy/runtime-licenses.v1.json`; do not edit manually.",
        "This inventory is not legal advice and does not replace upstream license texts.",
        "",
        "| Package | Version | License | Disposition |",
        "|---|---:|---|---|",
    ]
    for package in sorted(policy.packages, key=lambda item: item.name):
        lines.append(
            f"| `{package.name}` | `{package.version}` | `{package.license}` | `{package.status}` |"
        )
    decisions = [package for package in policy.packages if package.status != "allowed"]
    if decisions:
        lines.extend(["", "## Unresolved legal decisions", ""])
        for package in decisions:
            lines.extend(
                [
                    f"### {package.name} {package.version}",
                    "",
                    f"- Evidence: {package.evidence}",
                    f"- Exception expires: {package.exception_expires}",
                    f"- Owner: {package.owner}",
                    f"- Required disposition: {package.obligations}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"

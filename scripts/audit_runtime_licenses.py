"""Audit exact runtime licenses and drift-check generated notices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsvire.license_policy import DEFAULT_NOTICES, LicensePolicyError, audit, notices


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--write-notices", action="store_true")
    parser.add_argument("--require-release-ready", action="store_true")
    args = parser.parse_args()
    try:
        report = audit()
        expected_notices = notices()
    except LicensePolicyError as exc:
        parser.error(str(exc))
    if args.write_notices:
        DEFAULT_NOTICES.write_text(expected_notices, encoding="utf-8", newline="\n")
    elif (
        not DEFAULT_NOTICES.is_file()
        or DEFAULT_NOTICES.read_text(encoding="utf-8") != expected_notices
    ):
        parser.error("THIRD_PARTY_NOTICES.md drifted; run with --write-notices")
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.require_release_ready and not report["release_ready"]:
        parser.error("runtime license audit has unresolved legal decisions")
    disposition = "release-ready" if report["release_ready"] else "legal decision required"
    print(
        f"runtime license policy passed: {report['runtime_package_count']} packages; {disposition}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

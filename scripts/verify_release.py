"""Run the complete local/release verification gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from dsvire.release_verify import ReleaseVerificationError, verify_release, write_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = verify_release()
    except ReleaseVerificationError as exc:
        parser.error(str(exc))
    if args.json_out is not None:
        write_report(report, args.json_out)
    print("release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

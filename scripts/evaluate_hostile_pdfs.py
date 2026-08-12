"""Run deterministic malformed-PDF safety and resource evidence."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dsvire.hostile_pdf import HostilePdfError, run_campaign, write_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = asyncio.run(run_campaign())
    except HostilePdfError as exc:
        parser.error(str(exc))
    if args.json_out is not None:
        write_report(report, args.json_out)
    print(f"hostile PDF gate passed {report['case_count']} deterministic mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

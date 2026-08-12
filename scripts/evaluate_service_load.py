"""Run authenticated production-boundary DS-ViRe load evidence."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dsvire.load_evidence import LoadEvidenceError, run_service_load, write_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold-requests", type=int, default=3)
    parser.add_argument("--warm-requests", type=int, default=6)
    parser.add_argument("--overload-requests", type=int, default=6)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(
            run_service_load(
                cold_requests=args.cold_requests,
                warm_requests=args.warm_requests,
                overload_requests=args.overload_requests,
            )
        )
    except LoadEvidenceError as exc:
        parser.error(str(exc))
    write_report(report, args.json_out)
    print(
        "service load evidence passed: "
        f"{report['totals']['successful']} successful, "
        f"{report['totals']['overload_rejections']} bounded overload rejections"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

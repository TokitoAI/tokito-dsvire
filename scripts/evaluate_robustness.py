"""Run the source-generated, versioned PDF robustness corpus."""

from __future__ import annotations

import argparse
from pathlib import Path

from dsvire.robustness import DEFAULT_MANIFEST, RobustnessError, run_corpus, write_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = run_corpus(args.manifest)
    except RobustnessError as exc:
        parser.error(str(exc))
    if args.json_out is not None:
        write_report(report, args.json_out)
    print(f"robustness corpus passed {report['case_count']} generated cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

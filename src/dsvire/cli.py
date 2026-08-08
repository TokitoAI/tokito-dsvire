"""DS-ViRe command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import DatasheetIdentity, RetrievalError, retrieve_symbol_evidence


def main() -> int:
    parser = argparse.ArgumentParser(prog="dsvire")
    commands = parser.add_subparsers(dest="command", required=True)
    evidence = commands.add_parser("extract-evidence")
    evidence.add_argument("pdf", type=Path)
    evidence.add_argument("--manufacturer", required=True)
    evidence.add_argument("--mpn", required=True)
    evidence.add_argument("--package", required=True)
    evidence.add_argument("--source-url")
    evidence.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    try:
        bundle = retrieve_symbol_evidence(
            args.pdf.read_bytes(),
            DatasheetIdentity(args.manufacturer, args.mpn, args.package, args.source_url),
            args.out,
        )
    except (OSError, RetrievalError) as exc:
        parser.error(str(exc))
    print(json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

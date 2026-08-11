"""DS-ViRe command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import MAX_PDF_BYTES, DatasheetIdentity, RetrievalError, retrieve_symbol_evidence


def _read_pdf(path: Path) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(MAX_PDF_BYTES + 1)
    if len(payload) < 8 or len(payload) > MAX_PDF_BYTES:
        raise RetrievalError(f"PDF size outside 8..={MAX_PDF_BYTES} bytes")
    return payload


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
            _read_pdf(args.pdf),
            DatasheetIdentity(args.manufacturer, args.mpn, args.package, args.source_url),
            args.out,
        )
    except (OSError, RetrievalError) as exc:
        parser.error(str(exc))
    print(json.dumps(bundle, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

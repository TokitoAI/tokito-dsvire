"""DS-ViRe command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .pipeline import MAX_PDF_BYTES, DatasheetIdentity, RetrievalError, retrieve_symbol_evidence


async def _platform_init(slug: str, label: str) -> str:
    from .platform_config import PlatformConfig
    from .platform_db import PlatformDatabase

    config = PlatformConfig.from_env()
    database = await PlatformDatabase.connect(config.database_url, maximum=2)
    try:
        await database.migrate()
        tenant_id = await database.ensure_tenant(slug)
        return await database.issue_api_key(tenant_id, label)
    finally:
        await database.close()


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
    platform_init = commands.add_parser(
        "platform-init", help="migrate the platform DB and issue a tenant API key"
    )
    platform_init.add_argument("--tenant", required=True)
    platform_init.add_argument("--label", default="initial")
    args = parser.parse_args()

    if args.command == "platform-init":
        token = asyncio.run(_platform_init(args.tenant, args.label))
        print(token)
        return 0

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

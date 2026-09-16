"""DS-ViRe command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .ablation_gates import AblationGateError
from .cycle_execution import CycleExecutionError
from .pipeline import (
    MAX_PDF_BYTES,
    DatasheetIdentity,
    IdentityAmbiguous,
    IdentityHint,
    RetrievalError,
    retrieve_symbol_evidence,
)
from .symbol_compile import compile_symbol, public_candidates, write_symbol_bundle
from .training_cli import add_training_commands, run_training_command
from .training_corpus import TrainingCorpusError
from .training_runtime import TrainingRunError


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
    compile_cmd = commands.add_parser(
        "compile-symbol", help="compile a schematic SVG and JSON from a datasheet PDF"
    )
    compile_cmd.add_argument("pdf", type=Path)
    compile_cmd.add_argument("--manufacturer", default="")
    compile_cmd.add_argument("--mpn", default="")
    compile_cmd.add_argument("--package", default="")
    compile_cmd.add_argument("--source-url")
    compile_cmd.add_argument("--out", type=Path, required=True)
    platform_init = commands.add_parser(
        "platform-init", help="migrate the platform DB and issue a tenant API key"
    )
    platform_init.add_argument("--tenant", required=True)
    platform_init.add_argument("--label", default="initial")
    add_training_commands(commands)
    args = parser.parse_args()

    if args.command in {
        "cycle-v4-status",
        "cycle-v5-status",
        "corpus-audit",
        "training-bind",
        "ablation-gates",
    }:
        try:
            return run_training_command(args)
        except (
            CycleExecutionError,
            TrainingCorpusError,
            TrainingRunError,
            AblationGateError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            parser.error(str(exc))

    if args.command == "platform-init":
        token = asyncio.run(_platform_init(args.tenant, args.label))
        print(token)
        return 0

    if args.command == "compile-symbol":
        try:
            result = compile_symbol(
                _read_pdf(args.pdf),
                args.out,
                IdentityHint(args.manufacturer, args.mpn, args.package, args.source_url),
            )
        except IdentityAmbiguous as exc:
            print(
                json.dumps(
                    {"code": "ambiguous_identity", "candidates": public_candidates(exc)},
                    indent=2,
                )
            )
            return 2
        except (OSError, RetrievalError) as exc:
            parser.error(str(exc))
        write_symbol_bundle(result, args.out)
        print(
            json.dumps(
                {key: value for key, value in result.items() if key != "evidence"},
                indent=2,
            )
        )
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

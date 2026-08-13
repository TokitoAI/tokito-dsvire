"""Prepare or seal a score-free retrieval-cycle authoring packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from dsvire.pdf_backend import PdfDocument
from dsvire.retrieval_authoring import (
    RetrievalAuthoringError,
    build_authoring_packet,
    finalize_submission,
    load_authoring_packet,
    load_authoring_seal,
    seal_submission,
    submission_template,
)
from dsvire.visual_review import fetch_github_review_provenance

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    os.close(handle)
    temporary = Path(name)
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument(
        "--plan", type=Path, default=ROOT / "evaluation/retrieval_cycle_v4_preregistration.json"
    )
    prepare.add_argument(
        "--manifest", type=Path, default=ROOT / "evaluation/retrieval_cycle_v4_source_manifest.json"
    )
    prepare.add_argument("--source-dir", type=Path, required=True)
    prepare.add_argument("--packet-out", type=Path, required=True)
    prepare.add_argument("--template-out", type=Path, required=True)
    prepare.add_argument("--pages-out", type=Path, required=True)
    validate = commands.add_parser("validate-packet")
    validate.add_argument("--packet", type=Path, required=True)
    finalize = commands.add_parser("finalize-submission")
    finalize.add_argument("--packet", type=Path, required=True)
    finalize.add_argument("--submission", type=Path, required=True)
    finalize.add_argument("--out", type=Path, required=True)
    seal = commands.add_parser("seal")
    seal.add_argument("--packet", type=Path, required=True)
    seal.add_argument("--submission", type=Path, required=True)
    seal.add_argument("--review", type=Path, required=True)
    seal.add_argument("--out", type=Path, required=True)
    validate_seal = commands.add_parser("validate-seal")
    validate_seal.add_argument("--packet", type=Path, required=True)
    validate_seal.add_argument("--submission", type=Path, required=True)
    validate_seal.add_argument("--seal", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            packet = build_authoring_packet(
                _read(args.plan),
                _read(args.manifest),
                lambda digest: (args.source_dir / f"{digest}.pdf").read_bytes(),
            )
            _write(args.packet_out, packet)
            _write(args.template_out, submission_template(packet))
            args.pages_out.mkdir(parents=True, exist_ok=True)
            for document in packet["documents"]:
                payload = (args.source_dir / f"{document['source_sha256']}.pdf").read_bytes()
                with PdfDocument(payload) as pdf:
                    destination = args.pages_out / document["id"]
                    destination.mkdir(parents=True, exist_ok=True)
                    for expected, page_record in enumerate(document["pages"]):
                        with pdf.load_page(expected) as page:
                            png = page.render_png(
                                (0.0, 0.0, page.rect.width, page.rect.height), dpi=96
                            )
                        if hashlib.sha256(png).hexdigest() != page_record["render_sha256"]:
                            raise RetrievalAuthoringError(
                                "rendered page digest changed during export"
                            )
                        (destination / f"page-{expected + 1:04d}.png").write_bytes(png)
            print(args.packet_out)
        elif args.command == "validate-packet":
            packet = load_authoring_packet(_read(args.packet))
            print(packet["packet_sha256"])
        elif args.command == "finalize-submission":
            result = finalize_submission(_read(args.submission), _read(args.packet))
            _write(args.out, result)
            print(result["submission_sha256"])
        elif args.command == "seal":
            result = seal_submission(
                _read(args.packet),
                _read(args.submission),
                _read(args.review),
                lambda url: fetch_github_review_provenance(url, os.environ.get("GITHUB_TOKEN")),
            )
            _write(args.out, result)
            print(args.out)
        else:
            result = load_authoring_seal(
                _read(args.seal), _read(args.packet), _read(args.submission)
            )
            print(result["seal_sha256"])
    except (OSError, ValueError, RetrievalAuthoringError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

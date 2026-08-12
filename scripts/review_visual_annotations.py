"""Export, validate, and apply tamper-evident visual-annotation reviews."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from dsvire.eval_download import fetch_hash_pinned_pdf
from dsvire.visual_registry import VisualDocument, load_visual_registry_data
from dsvire.visual_review import (
    VisualReviewError,
    apply_agent_review_decision,
    apply_review_decision,
    build_review_packet,
    fetch_github_review_provenance,
    load_review_decision_data,
    load_review_packet_data,
    write_review_sheet,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "evaluation" / "visual_registry.v1.json"


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".part"
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export")
    export.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    export.add_argument("--cache-dir", type=Path, required=True)
    export.add_argument("--out-dir", type=Path, required=True)
    export.add_argument("--packet-out", type=Path, required=True)
    export.add_argument("--document-id", action="append")
    export.add_argument("--offline", action="store_true")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--packet", type=Path, required=True)
    validate.add_argument("--decision", type=Path, required=True)

    attest = subparsers.add_parser("attest")
    attest.add_argument("--packet", type=Path, required=True)
    attest.add_argument("--reviewer", required=True)
    attest.add_argument("--reviewed-at", required=True)
    attest.add_argument("--review-url", required=True)
    attest.add_argument("--out", type=Path, required=True)

    apply = subparsers.add_parser("apply")
    apply.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    apply.add_argument("--packet", type=Path, required=True)
    apply.add_argument("--decision", type=Path, required=True)
    apply.add_argument("--out", type=Path, required=True)

    apply_agent = subparsers.add_parser("apply-agent")
    apply_agent.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    apply_agent.add_argument("--packet", type=Path, required=True)
    apply_agent.add_argument("--decision", type=Path, required=True)
    apply_agent.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "export":
            registry = load_visual_registry_data(
                _read(args.registry), allow_unreviewed_heldout_draft=True
            )
            selected = set(args.document_id) if args.document_id else None
            payloads: dict[str, bytes] = {}

            def load(document: VisualDocument) -> bytes:
                if document.document_id not in payloads:
                    payloads[document.document_id] = fetch_hash_pinned_pdf(
                        case_id=document.document_id,
                        source_url=document.source.url,
                        content_sha256=document.content_sha256,
                        cache_dir=args.cache_dir,
                        offline=args.offline,
                    )
                return payloads[document.document_id]

            packet = build_review_packet(registry, load, document_ids=selected)
            packet_documents = cast(list[dict[str, Any]], packet["documents"])
            packet_ids = {document["id"] for document in packet_documents}
            for document in registry.documents:
                if document.document_id in packet_ids:
                    write_review_sheet(load(document), document, args.out_dir)
            _write_atomic(args.packet_out, packet)
            print(args.packet_out)
        elif args.command == "attest":
            packet = load_review_packet_data(_read(args.packet))
            decision = {
                "schema_version": "dsvire.visual-review-decision.v1",
                "packet_sha256": packet["packet_sha256"],
                "registry_sha256": packet["registry_sha256"],
                "reviewer": args.reviewer,
                "reviewed_at": args.reviewed_at,
                "review_url": args.review_url,
                "decisions": [
                    {"case_id": case["case_id"], "outcome": "accepted", "note": ""}
                    for document in cast(list[dict[str, Any]], packet["documents"])
                    for case in document["cases"]
                ],
            }
            load_review_decision_data(decision, packet)
            _write_atomic(args.out, decision)
            print(args.out)
        elif args.command == "validate":
            packet = load_review_packet_data(_read(args.packet))
            load_review_decision_data(_read(args.decision), packet)
            print("review decision valid")
        elif args.command == "apply":
            output = apply_review_decision(
                _read(args.registry),
                _read(args.packet),
                _read(args.decision),
                provenance_loader=lambda url: fetch_github_review_provenance(
                    url, os.environ.get("GITHUB_TOKEN")
                ),
            )
            _write_atomic(args.out, output)
            print(args.out)
        else:
            output = apply_agent_review_decision(
                _read(args.registry),
                _read(args.packet),
                _read(args.decision),
            )
            _write_atomic(args.out, output)
            print(args.out)
    except (OSError, ValueError, RuntimeError, VisualReviewError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

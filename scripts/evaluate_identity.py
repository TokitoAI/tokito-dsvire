"""Run the hash-pinned real-PDF identity evaluation registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path

from dsvire.evaluation import DocumentCase, RegistryError, evaluate_registry, load_registry_data
from dsvire.pipeline import MAX_PDF_BYTES

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "evaluation" / "identity_registry.v1.json"


def _download(case: DocumentCase, cache_dir: Path, *, offline: bool) -> bytes:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{case.content_sha256}.pdf"
    if path.is_file():
        if path.stat().st_size > MAX_PDF_BYTES:
            raise RegistryError(f"{case.case_id}: cached PDF exceeds size limit")
        return path.read_bytes()
    if offline:
        raise RegistryError(f"{case.case_id}: PDF is not cached in offline mode")
    request = urllib.request.Request(
        case.source_url,
        headers={"User-Agent": "Tokito-DSViRe-Evaluation/1.0"},
    )
    temporary = path.with_suffix(f".tmp-{os.getpid()}")
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            temporary.open("xb") as target,
        ):
            if not response.geturl().startswith("https://"):
                raise RegistryError(f"{case.case_id}: download redirected away from HTTPS")
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise RegistryError(f"{case.case_id}: download exceeds PDF size limit")
                target.write(chunk)
        payload = temporary.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != case.content_sha256:
            raise RegistryError(
                f"{case.case_id}: downloaded SHA-256 mismatch; "
                f"expected {case.content_sha256}, got {digest}"
            )
        temporary.replace(path)
        return payload
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    try:
        registry = load_registry_data(json.loads(args.registry.read_text(encoding="utf-8")))
        result = evaluate_registry(
            registry,
            lambda case: _download(case, args.cache_dir, offline=args.offline),
            output_root=args.output_root,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out is not None:
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

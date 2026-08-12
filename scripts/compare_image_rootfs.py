"""Compare two Docker-exported root filesystems with bounded evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any

SCHEMA = "dsvire.image-reproducibility.v1"
RUNTIME_INJECTED_PATHS = frozenset({"etc/hostname", "etc/hosts", "etc/resolv.conf"})


def _member_type(member: tarfile.TarInfo) -> str:
    if member.isfile():
        return "file"
    if member.isdir():
        return "directory"
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hardlink"
    if member.ischr():
        return "character-device"
    if member.isblk():
        return "block-device"
    if member.isfifo():
        return "fifo"
    return f"tar-type-{member.type!r}"


def inventory(path: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    with tarfile.open(path, mode="r:*") as archive:
        for member in archive:
            name = member.name.removeprefix("./").rstrip("/")
            if not name or name in RUNTIME_INJECTED_PATHS:
                continue
            if name in entries:
                raise ValueError(f"duplicate rootfs path: {name}")
            entry: dict[str, Any] = {
                "type": _member_type(member),
                "mode": member.mode,
                "uid": member.uid,
                "gid": member.gid,
            }
            if member.linkname:
                entry["link_target"] = member.linkname
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"cannot read rootfs file: {name}")
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                entry["sha256"] = digest.hexdigest()
                entry["size"] = member.size
            entries[name] = entry
    if not entries:
        raise ValueError("rootfs inventory is empty")
    return entries


def inventory_digest(entries: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def compare(
    first: Path,
    second: Path,
    *,
    source_commit: str,
    base_image: str,
    first_image_id: str,
    second_image_id: str,
) -> dict[str, Any]:
    first_entries = inventory(first)
    second_entries = inventory(second)
    differing_paths = sorted(
        name
        for name in set(first_entries) | set(second_entries)
        if first_entries.get(name) != second_entries.get(name)
    )
    first_digest = inventory_digest(first_entries)
    second_digest = inventory_digest(second_entries)
    return {
        "schema_version": SCHEMA,
        "ok": not differing_paths and first_digest == second_digest,
        "source_commit": source_commit,
        "base_image": base_image,
        "excluded_runtime_injected_paths": sorted(RUNTIME_INJECTED_PATHS),
        "first": {
            "image_id": first_image_id,
            "entry_count": len(first_entries),
            "rootfs_digest": first_digest,
        },
        "second": {
            "image_id": second_image_id,
            "entry_count": len(second_entries),
            "rootfs_digest": second_digest,
        },
        "differing_path_count": len(differing_paths),
        "differing_paths": differing_paths[:100],
        "differing_paths_truncated": len(differing_paths) > 100,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--first-image-id", required=True)
    parser.add_argument("--second-image-id", required=True)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--inventory-out", type=Path)
    args = parser.parse_args()
    try:
        report = compare(
            args.first,
            args.second,
            source_commit=args.source_commit,
            base_image=args.base_image,
            first_image_id=args.first_image_id,
            second_image_id=args.second_image_id,
        )
    except (OSError, tarfile.TarError, ValueError) as exc:
        parser.error(str(exc))
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.inventory_out is not None:
        args.inventory_out.write_text(
            json.dumps(inventory(args.first), sort_keys=True) + "\n", encoding="utf-8"
        )
    if not report["ok"]:
        parser.error(
            f"root filesystems differ at {report['differing_path_count']} paths; "
            f"see {args.json_out}"
        )
    print(
        f"reproducible rootfs: {report['first']['entry_count']} entries, "
        f"sha256:{report['first']['rootfs_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

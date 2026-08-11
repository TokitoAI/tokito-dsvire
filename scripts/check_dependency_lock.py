"""Fail when the universal lock or container export has drifted."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LOCK = ROOT / "requirements" / "runtime.lock"


def run(*args: str, quiet: bool = False) -> None:
    subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL if quiet else None,
    )


def main() -> int:
    run("uv", "lock", "--check")
    with tempfile.TemporaryDirectory(prefix="dsvire-lock-") as directory:
        exported = Path(directory) / "runtime.lock"
        run(
            "uv",
            "export",
            "--locked",
            "--format",
            "requirements.txt",
            "--no-dev",
            "--no-emit-project",
            "--no-header",
            "--output-file",
            str(exported),
            quiet=True,
        )
        if exported.read_bytes() != RUNTIME_LOCK.read_bytes():
            print(
                "requirements/runtime.lock is stale; run "
                "'uv export --locked --format requirements.txt --no-dev "
                "--no-emit-project --no-header --output-file requirements/runtime.lock'",
                file=sys.stderr,
            )
            return 1
    print("dependency lock and runtime export are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

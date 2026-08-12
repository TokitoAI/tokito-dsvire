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


def locks_equal(first: Path, second: Path) -> bool:
    """Compare generated lock text without platform-specific newline noise."""
    return (
        first.read_text(encoding="utf-8").splitlines()
        == second.read_text(encoding="utf-8").splitlines()
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
        # Git may check this generated text file out with CRLF on Windows while
        # uv always exports LF. Compare decoded lines so platform newlines do
        # not masquerade as dependency drift; every package/hash byte remains
        # covered by the comparison.
        if not locks_equal(exported, RUNTIME_LOCK):
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

"""End-to-end Tokito symbol pipeline runner.

Orchestrates a full slice for one fixture:

    fixture (bundle) -> extract -> compile -> ingest -> sync -> resolve
                                                          -> provenance

Each stage is a real subprocess call. Stage commands are configurable via env
vars so the runner keeps working as teammates land their crates:

    TOKITO_EXTRACT_CMD    (default: tokito-symbol-extractor)
    TOKITO_COMPILE_CMD    (default: tokito-symbol-compile)
    TOKITO_AI_URL         (default: http://localhost:8080)
    TOKITO_AI_TOKEN       (required for the ingest stage)
    TOKITO_MCP_PACK_CMD   (default: tokito-mcp-pack)
    TOKITO_MCP_URL        (default: http://localhost:8090/mcp)

If a stage's tool is not on PATH or the endpoint is unreachable, the runner
fails loudly with an actionable message — never a silent fallback or fabricated
artifact. Every artifact is written under artifacts/<slug>/ and inspected by
scripts/verify.py at the end.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "evidence"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Config:
    extract_cmd: str
    compile_cmd: str
    tokito_ai_url: str
    tokito_ai_token: str | None
    mcp_pack_cmd: str
    mcp_url: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = env if env is not None else os.environ
        return cls(
            extract_cmd=e.get("TOKITO_EXTRACT_CMD", "tokito-symbol-extractor"),
            compile_cmd=e.get("TOKITO_COMPILE_CMD", "tokito-symbol-compile"),
            tokito_ai_url=e.get("TOKITO_AI_URL", "http://localhost:8080"),
            tokito_ai_token=e.get("TOKITO_AI_TOKEN"),
            mcp_pack_cmd=e.get("TOKITO_MCP_PACK_CMD", "tokito-mcp-pack"),
            mcp_url=e.get("TOKITO_MCP_URL", "http://localhost:8090/mcp"),
        )


# ---------------------------------------------------------------------------
# Stage errors
# ---------------------------------------------------------------------------

class StageError(RuntimeError):
    """Raised when a stage cannot proceed. Bubbles up with a clear message."""


def _require_tool(name: str) -> str:
    """Resolve a command word to an absolute path or raise a clear StageError."""
    # Commands may include args ("cargo run --bin foo"). Split and check the first token.
    parts = shlex.split(name)
    if not parts:
        raise StageError(f"empty command string {name!r}")
    resolved = shutil.which(parts[0])
    if resolved is None:
        raise StageError(
            f"required tool {parts[0]!r} not found on PATH — set the matching "
            f"TOKITO_*_CMD env var to an available binary or install the tool. "
            f"Full command was: {name}"
        )
    return name


def _run(command: str, /, **kwargs) -> subprocess.CompletedProcess:
    """Run a shell-like command with clear failure semantics."""
    result = subprocess.run(shlex.split(command), check=False, **kwargs)
    if result.returncode != 0:
        raise StageError(
            f"command failed (rc={result.returncode}): {command}\n"
            f"--- stdout ---\n{(result.stdout or '').strip()}\n"
            f"--- stderr ---\n{(result.stderr or '').strip()}"
        )
    return result


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def stage_extract(cfg: Config, bundle_path: Path, out_dir: Path) -> Path:
    _require_tool(cfg.extract_cmd)
    out = out_dir / "spec.json"
    _run(
        f"{cfg.extract_cmd} extract "
        f"--evidence {shlex.quote(str(bundle_path))} "
        f"--out {shlex.quote(str(out))}",
        capture_output=True, text=True,
    )
    if not out.exists():
        raise StageError(f"extract stage did not produce {out}")
    return out


def stage_compile(cfg: Config, spec_path: Path, out_dir: Path) -> Path:
    _require_tool(cfg.compile_cmd)
    out = out_dir / "symbol.tokito_sym"
    _run(
        f"{cfg.compile_cmd} "
        f"--spec {shlex.quote(str(spec_path))} "
        f"--out {shlex.quote(str(out))}",
        capture_output=True, text=True,
    )
    if not out.exists():
        raise StageError(f"compile stage did not produce {out}")
    return out


def stage_ingest(
    cfg: Config,
    spec_path: Path,
    bundle_path: Path,
    out_dir: Path,
) -> Path:
    if not cfg.tokito_ai_token:
        raise StageError(
            "TOKITO_AI_TOKEN is not set; ingest requires an authenticated JWT."
        )
    _require_tool("curl")
    payload = {
        "spec": json.loads(spec_path.read_text(encoding="utf-8")),
        "evidence": json.loads(bundle_path.read_text(encoding="utf-8")),
    }
    payload_path = out_dir / "ingest_payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    response_path = out_dir / "ingest_response.json"
    _run(
        f"curl --fail --silent --show-error "
        f"--header 'Authorization: Bearer {cfg.tokito_ai_token}' "
        f"--header 'Content-Type: application/json' "
        f"--data-binary @{shlex.quote(str(payload_path))} "
        f"--output {shlex.quote(str(response_path))} "
        f"{shlex.quote(cfg.tokito_ai_url.rstrip('/') + '/v1/generated/ingest')}",
        capture_output=True, text=True,
    )
    response = json.loads(response_path.read_text(encoding="utf-8"))
    if "revision_id" not in response:
        raise StageError(f"ingest response missing revision_id: {response}")
    return response_path


def stage_sync(cfg: Config) -> None:
    _require_tool(cfg.mcp_pack_cmd)
    _run(f"{cfg.mcp_pack_cmd} --generated", capture_output=True, text=True)


def _mcp_call(cfg: Config, tool: str, arguments: dict) -> dict:
    """Invoke an MCP tool over the streamable HTTP transport."""
    _require_tool("curl")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    result = _run(
        f"curl --fail --silent --show-error "
        f"--header 'Content-Type: application/json' "
        f"--header 'Accept: application/json' "
        f"--data-binary {shlex.quote(json.dumps(request))} "
        f"{shlex.quote(cfg.mcp_url)}",
        capture_output=True, text=True,
    )
    doc = json.loads(result.stdout)
    if "error" in doc:
        raise StageError(f"MCP tool {tool!r} returned error: {doc['error']}")
    return doc["result"]


def stage_resolve(cfg: Config, spec: dict, out_dir: Path) -> Path:
    payload = {
        "manufacturer": spec["manufacturer"],
        "mpn": spec["mpn"],
        "package": spec["package"],
    }
    result = _mcp_call(cfg, "resolve_by_mpn", payload)
    out = out_dir / "resolved.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out


def stage_provenance(cfg: Config, revision_id: str, out_dir: Path) -> Path:
    result = _mcp_call(cfg, "get_symbol_provenance", {"revision_id": revision_id})
    out = out_dir / "provenance.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

STAGE_ORDER = (
    "extract", "compile", "ingest", "sync", "resolve", "provenance", "verify",
)


def run(slug: str, cfg: Config, artifacts_root: Path, stages: Iterable[str]) -> int:
    bundle_path = FIXTURE_DIR / f"{slug}.json"
    if not bundle_path.exists():
        print(
            f"fixture {slug!r} not found at {bundle_path}. "
            f"Run `python3 scripts/build_fixture.py {slug}` first.",
            file=sys.stderr,
        )
        return 2
    out_dir = artifacts_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    ran: dict[str, Path | None] = {}

    for stage in stages:
        print(f"→ {stage}", flush=True)
        try:
            if stage == "extract":
                ran["spec"] = stage_extract(cfg, bundle_path, out_dir)
            elif stage == "compile":
                spec = ran.get("spec") or (out_dir / "spec.json")
                ran["symbol"] = stage_compile(cfg, spec, out_dir)
            elif stage == "ingest":
                spec = ran.get("spec") or (out_dir / "spec.json")
                ran["ingest"] = stage_ingest(cfg, spec, bundle_path, out_dir)
            elif stage == "sync":
                stage_sync(cfg)
            elif stage == "resolve":
                spec_path = ran.get("spec") or (out_dir / "spec.json")
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                ran["resolved"] = stage_resolve(cfg, spec, out_dir)
            elif stage == "provenance":
                ingest_path = ran.get("ingest") or (out_dir / "ingest_response.json")
                if not ingest_path.exists():
                    raise StageError(
                        f"provenance stage needs {ingest_path.name} from a prior ingest run"
                    )
                revision_id = json.loads(ingest_path.read_text(encoding="utf-8"))["revision_id"]
                ran["provenance"] = stage_provenance(cfg, revision_id, out_dir)
            elif stage == "verify":
                sys.path.insert(0, str(REPO_ROOT / "scripts"))
                import verify as v  # local import: avoids startup cost
                paths = v.ArtifactPaths(
                    bundle=bundle_path,
                    spec=out_dir / "spec.json",
                    symbol=out_dir / "symbol.tokito_sym",
                    provenance=out_dir / "provenance.json",
                    resolved=out_dir / "resolved.json",
                )
                report = v.verify_slice(paths)
                for f in report.findings:
                    print(f"    [{f.outcome.value:7s}] {f.check_id:45s} {f.detail}")
                print(f"  RESULT: {'PASS' if report.ok else 'FAIL'}")
                if not report.ok:
                    return 1
            else:
                print(f"unknown stage: {stage}", file=sys.stderr)
                return 2
        except StageError as e:
            print(f"  ✗ {stage} failed: {e}", file=sys.stderr)
            return 1

    return 0


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="fixture slug, e.g. tps5430ddar")
    ap.add_argument(
        "--artifacts",
        type=Path,
        default=ARTIFACTS_ROOT,
        help="root artifact dir (default: <repo>/artifacts)",
    )
    ap.add_argument(
        "--stages",
        nargs="+",
        default=list(STAGE_ORDER),
        choices=STAGE_ORDER,
        help="subset of stages to run (default: all)",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    return run(args.slug, Config.from_env(), args.artifacts, args.stages)


if __name__ == "__main__":
    raise SystemExit(main())

"""End-to-end Tokito symbol pipeline runner.

Orchestrates a full slice for one fixture:

    fixture (bundle) -> extract -> compile -> ingest -> sync -> resolve
                                                          -> provenance

Each stage is a real subprocess call. Stage commands are configurable via env
vars so the runner keeps working as teammates land their crates:

    TOKITO_EXTRACT_CMD    (default: tokito-symbol-extractor)
    TOKITO_COMPILE_CMD    (default: tokito-symbol-compile)
    TOKITO_AI_URL         (default: https://api.tokito.dev)
    TOKITO_AI_TOKEN       (required for the ingest stage)
    TOKITO_MCP_PACK_CMD   (default: tokito-mcp-pack)
    TOKITO_MCP_URL        (default: https://mcp.tokito.dev/mcp)
    TOKITO_MCP_DB         (operator-only sync: served symbols.sqlite)
    TOKITO_GENERATED_DB   (operator-only sync: tokito-ai generated.sqlite)

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
import urllib.error
import urllib.request
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
    mcp_db: str | None
    generated_db: str | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = env if env is not None else os.environ
        return cls(
            extract_cmd=e.get("TOKITO_EXTRACT_CMD", "tokito-symbol-extractor"),
            compile_cmd=e.get("TOKITO_COMPILE_CMD", "tokito-symbol-compile"),
            tokito_ai_url=e.get("TOKITO_AI_URL", "https://api.tokito.dev"),
            tokito_ai_token=e.get("TOKITO_AI_TOKEN"),
            mcp_pack_cmd=e.get("TOKITO_MCP_PACK_CMD", "tokito-mcp-pack"),
            mcp_url=e.get("TOKITO_MCP_URL", "https://mcp.tokito.dev/mcp"),
            mcp_db=e.get("TOKITO_MCP_DB"),
            generated_db=e.get("TOKITO_GENERATED_DB"),
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
    payload = {
        "spec": json.loads(spec_path.read_text(encoding="utf-8")),
        "evidence": json.loads(bundle_path.read_text(encoding="utf-8")),
    }
    payload_path = out_dir / "ingest_payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    response_path = out_dir / "ingest_response.json"
    response = _http_json(
        cfg.tokito_ai_url.rstrip("/") + "/v1/generated/ingest",
        payload,
        headers={"Authorization": f"Bearer {cfg.tokito_ai_token}"},
    )
    response_path.write_text(json.dumps(response, indent=2), encoding="utf-8")
    if "revision_id" not in response:
        raise StageError(f"ingest response missing revision_id: {response}")
    return response_path


def stage_sync(cfg: Config) -> None:
    _require_tool(cfg.mcp_pack_cmd)
    if not cfg.mcp_db or not cfg.generated_db:
        raise StageError(
            "sync requires TOKITO_MCP_DB (served symbols.sqlite) and "
            "TOKITO_GENERATED_DB (tokito-ai generated.sqlite)"
        )
    command = shlex.split(cfg.mcp_pack_cmd) + [
        "generated",
        "--db",
        cfg.mcp_db,
        "--source",
        cfg.generated_db,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise StageError(
            f"generated-symbol sync failed (rc={result.returncode}): "
            f"{shlex.join(command)}\n--- stdout ---\n{result.stdout.strip()}\n"
            f"--- stderr ---\n{result.stderr.strip()}"
        )


def _http_json(
    url: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
    session_id: str | None = None,
) -> tuple[dict, str | None] | dict:
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "tokito-dsvire-demo/0.1.0",
        **(headers or {}),
    }
    if session_id:
        request_headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            response_session = response.headers.get("Mcp-Session-Id")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4096]
        raise StageError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise StageError(f"cannot reach {url}: {exc.reason}") from exc

    content_type = response.headers.get_content_type()
    if content_type == "text/event-stream" or raw.lstrip().startswith("event:"):
        messages = []
        for line in raw.splitlines():
            if line.startswith("data:"):
                value = line.removeprefix("data:").strip()
                if value and value != "[DONE]":
                    messages.append(json.loads(value))
        if not messages:
            raise StageError(f"MCP response from {url} contained no JSON event")
        document = messages[-1]
    else:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StageError(f"non-JSON response from {url}: {raw[:4096]}") from exc
    if response_session is not None:
        return document, response_session
    return document


def _mcp_call(cfg: Config, tool: str, arguments: dict) -> dict:
    """Invoke an MCP tool over the streamable HTTP transport."""
    initialized = _http_json(
        cfg.mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "tokito-dsvire-demo", "version": "0.1.0"},
            },
        },
    )
    if not isinstance(initialized, tuple) or not initialized[1]:
        raise StageError("MCP initialize response did not include Mcp-Session-Id")
    init_body, session_id = initialized
    if "error" in init_body:
        raise StageError(f"MCP initialize returned error: {init_body['error']}")

    # Streamable HTTP clients notify the server that initialization is
    # complete before invoking tools. A notification has no response body;
    # tolerate an empty 202 response via a small dedicated request.
    notification = urllib.request.Request(
        cfg.mcp_url,
        data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
            "User-Agent": "tokito-dsvire-demo/0.1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(notification, timeout=30):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4096]
        raise StageError(f"MCP initialized notification failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise StageError(f"MCP initialized notification failed: {exc.reason}") from exc

    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    doc = _http_json(cfg.mcp_url, request, session_id=session_id)
    if isinstance(doc, tuple):
        doc = doc[0]
    if "error" in doc:
        raise StageError(f"MCP tool {tool!r} returned error: {doc['error']}")
    result = doc.get("result", {})
    if result.get("isError"):
        raise StageError(f"MCP tool {tool!r} failed: {result.get('content')}")
    content = result.get("content", [])
    text_items = [item.get("text") for item in content if item.get("type") == "text"]
    if not text_items:
        raise StageError(f"MCP tool {tool!r} returned no text payload: {result}")
    try:
        return json.loads(text_items[0])
    except json.JSONDecodeError as exc:
        raise StageError(f"MCP tool {tool!r} returned non-JSON text: {text_items[0]}") from exc


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

"""Run the seeded Wave D acceptance across the real Tokito repositories.

This is deliberately not a mock pipeline.  The only seeded boundary is the
checked evidence/spec pair: publication, SQLite persistence, packing, MCP
streamable HTTP, provenance, and Desktop place/save/reopen all execute their
production code paths.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import demo_run  # noqa: E402
import verify  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Repositories:
    dsvire: Path
    tokito: Path
    ai: Path
    catalog: Path
    mcp: Path

    @classmethod
    def discover(cls, root: Path = REPO_ROOT) -> Repositories:
        siblings = root.parent
        repos = cls(
            dsvire=root,
            tokito=siblings / "tokito",
            ai=siblings / "tokito-ai",
            catalog=siblings / "tokito-catalog",
            mcp=siblings / "tokito-mcp",
        )
        missing = [str(path) for path in dataclasses.astuple(repos) if not Path(path).is_dir()]
        if missing:
            raise demo_run.StageError(
                "missing sibling repository checkout(s): " + ", ".join(missing)
            )
        return repos


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def issue_acceptance_jwt(secret: str, now: int) -> str:
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    claims = _b64url(
        json.dumps(
            {
                "sub": "wave-d-acceptance@tokito.dev",
                "plan": "internal",
                "iat": now,
                "exp": now + 900,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{claims}"
    signature = _b64url(
        hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{signing_input}.{signature}"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run(args: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise demo_run.StageError(
            f"command failed ({result.returncode}) in {cwd}: {subprocess.list2cmdline(args)}\n"
            f"--- stdout ---\n{result.stdout[-12000:]}\n--- stderr ---\n{result.stderr[-12000:]}"
        )
    return result.stdout


def _wait_http(url: str, process: subprocess.Popen[str], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            raise demo_run.StageError(
                f"service exited before readiness ({process.returncode})\n"
                f"--- stdout ---\n{stdout[-8000:]}\n--- stderr ---\n{stderr[-8000:]}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except Exception as error:  # readiness polling reports the final cause
            last_error = str(error)
        time.sleep(0.1)
    raise demo_run.StageError(f"service was not ready at {url} within {timeout}s: {last_error}")


def _stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit(repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], repo).strip()


def run(repos: Repositories, output: Path, report_path: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    timings: dict[str, float] = {}

    def stage(name: str, action: Any) -> Any:
        print(f"[wave-d] {name}", flush=True)
        at = time.monotonic()
        value = action()
        timings[name] = round(time.monotonic() - at, 3)
        return value

    fixture = repos.dsvire / "fixtures" / "acceptance" / "tps5430ddar.egvv.json"
    seed_spec = repos.dsvire / "fixtures" / "acceptance" / "tps5430ddar.spec.json"
    spec = output / "spec.json"
    shutil.copyfile(seed_spec, spec)

    stage(
        "build catalog compiler",
        lambda: _run(
            ["cargo", "build", "--locked", "--bin", "tokito-symbol-compile"], repos.catalog
        ),
    )
    stage(
        "build Cloud API",
        lambda: _run(["cargo", "build", "--locked", "--bin", "tokito-ai-api"], repos.ai),
    )
    stage(
        "build MCP packer/server",
        lambda: _run(
            [
                "cargo",
                "build",
                "--locked",
                "--bin",
                "tokito-mcp-pack",
                "--bin",
                "tokito-mcp-server",
            ],
            repos.mcp,
        ),
    )

    compiler = (
        repos.catalog
        / "target"
        / "debug"
        / ("tokito-symbol-compile.exe" if os.name == "nt" else "tokito-symbol-compile")
    )
    api = (
        repos.ai
        / "target"
        / "debug"
        / ("tokito-ai-api.exe" if os.name == "nt" else "tokito-ai-api")
    )
    packer = (
        repos.mcp
        / "target"
        / "debug"
        / ("tokito-mcp-pack.exe" if os.name == "nt" else "tokito-mcp-pack")
    )
    mcp_server = (
        repos.mcp
        / "target"
        / "debug"
        / ("tokito-mcp-server.exe" if os.name == "nt" else "tokito-mcp-server")
    )

    symbol = output / "symbol.tokito_sym"
    stage(
        "compile",
        lambda: _run([str(compiler), "--spec", str(spec), "--out", str(symbol)], repos.catalog),
    )

    official_db = output / "symbols.sqlite"
    catalog_fixture = repos.dsvire / "fixtures" / "acceptance" / "catalog"
    stage(
        "build official catalog",
        lambda: _run(
            [
                str(packer),
                "--src",
                str(catalog_fixture),
                "--out",
                str(official_db),
                "--source-commit",
                "wave-d-acceptance",
            ],
            repos.mcp,
        ),
    )

    ai_port = _free_port()
    jwt_secret = "wave-d-local-jwt-secret-not-for-production"
    ai_env = os.environ.copy()
    ai_env.update(
        {
            "TOKITO_AI_ADDR": f"127.0.0.1:{ai_port}",
            "TOKITO_AI_DATA_DIR": str(output / "ai-data"),
            "TOKITO_AI_JWT_SECRET": jwt_secret,
            "TOKITO_AI_UPSTREAM_API_KEY": "acceptance-no-network",
            "RUST_LOG": "warn",
        }
    )
    api_process: subprocess.Popen[str] | None = None
    mcp_process: subprocess.Popen[str] | None = None
    try:
        api_process = subprocess.Popen(
            [str(api)],
            cwd=repos.ai,
            env=ai_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stage(
            "Cloud readiness",
            lambda: _wait_http(f"http://127.0.0.1:{ai_port}/v1/health", api_process),
        )
        token = issue_acceptance_jwt(jwt_secret, int(time.time()))
        cfg = demo_run.Config(
            extract_cmd="unused-seeded-fixture",
            compile_cmd=str(compiler),
            tokito_ai_url=f"http://127.0.0.1:{ai_port}",
            tokito_ai_token=token,
            mcp_pack_cmd=str(packer),
            mcp_url="unused-until-server-starts",
            mcp_db=str(official_db),
            generated_db=str(output / "ai-data" / "generated.sqlite"),
        )
        ingest_path = stage(
            "authenticated ingest", lambda: demo_run.stage_ingest(cfg, spec, fixture, output)
        )
        ingest = json.loads(ingest_path.read_text(encoding="utf-8"))
        if ingest.get("pin_count") != 8 or ingest.get("status") != "published":
            raise demo_run.StageError(f"unexpected ingest response: {ingest}")
        stage(
            "generated catalog sync",
            lambda: _run(
                [
                    str(packer),
                    "generated",
                    "--db",
                    str(official_db),
                    "--source",
                    str(output / "ai-data" / "generated.sqlite"),
                ],
                repos.mcp,
            ),
        )

        mcp_port = _free_port()
        mcp_process = subprocess.Popen(
            [str(mcp_server), "--db", str(official_db), "--addr", f"127.0.0.1:{mcp_port}"],
            cwd=repos.mcp,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stage(
            "MCP readiness",
            lambda: _wait_http(f"http://127.0.0.1:{mcp_port}/v1/health", mcp_process),
        )
        cfg = dataclasses.replace(cfg, mcp_url=f"http://127.0.0.1:{mcp_port}/mcp")
        spec_document = json.loads(spec.read_text(encoding="utf-8"))
        resolved = stage(
            "MCP resolve_by_mpn", lambda: demo_run.stage_resolve(cfg, spec_document, output)
        )
        provenance = stage(
            "MCP get_symbol_provenance",
            lambda: demo_run.stage_provenance(cfg, str(ingest["revision_id"]), output),
        )

        report = stage(
            "artifact verification",
            lambda: verify.verify_slice(
                verify.ArtifactPaths(
                    bundle=fixture,
                    spec=spec,
                    symbol=symbol,
                    provenance=provenance,
                    resolved=resolved,
                )
            ),
        )
        if not report.ok:
            failed = [
                f"{finding.check_id}: {finding.detail}"
                for finding in report.findings
                if not finding.ok
            ]
            raise demo_run.StageError("artifact verifier failed: " + "; ".join(failed))

        desktop_env = os.environ.copy()
        desktop_env["TOKITO_WAVE_D_RESOLVED"] = str(resolved)
        stage(
            "Desktop place/save/reopen",
            lambda: _run(
                [
                    "cargo",
                    "test",
                    "--locked",
                    "-p",
                    "tokito-native",
                    "base_symbols::tests::generated_symbol_survives_desktop_place_save_reopen_and_svg",
                    "--",
                    "--exact",
                ],
                repos.tokito,
                env=desktop_env,
            ),
        )
    finally:
        _stop(mcp_process)
        _stop(api_process)

    artifacts = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in [
            fixture,
            spec,
            symbol,
            output / "ingest_response.json",
            output / "resolved.json",
            output / "provenance.json",
            official_db,
        ]
    }
    result = {
        "schema_version": "tokito.wave-d-acceptance.v1",
        "ok": True,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seeded_boundary": "checked EGVV evidence and SymbolSpec; no live model call",
        "repositories": {
            field.name: _commit(getattr(repos, field.name)) for field in dataclasses.fields(repos)
        },
        "timings_seconds": timings,
        "total_seconds": round(time.monotonic() - started, 3),
        "artifacts": artifacts,
        "verification": report.to_json(),
    }
    artifact_report = output / "wave-d-acceptance.json"
    serialized = json.dumps(result, indent=2) + "\n"
    artifact_report.write_text(serialized, encoding="utf-8")
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(serialized, encoding="utf-8")
    print(f"PASS: {artifact_report}")
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "artifacts" / "wave-d")
    parser.add_argument("--report", type=Path, help="also write the compact evidence report here")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        report = args.report.resolve() if args.report is not None else None
        run(Repositories.discover(), args.output.resolve(), report)
    except demo_run.StageError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

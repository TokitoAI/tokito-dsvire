from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import wave_d_acceptance as wave_d  # noqa: E402


def _decode(segment: str) -> dict[str, object]:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_acceptance_jwt_matches_tokito_ai_hs256_contract() -> None:
    token = wave_d.issue_acceptance_jwt("fixture-secret", 1000)
    header, payload, signature = token.split(".")
    assert _decode(header) == {"alg": "HS256", "typ": "JWT"}
    assert _decode(payload) == {
        "sub": "wave-d-acceptance@tokito.dev",
        "plan": "internal",
        "iat": 1000,
        "exp": 1900,
    }
    expected = hmac.new(
        b"fixture-secret", f"{header}.{payload}".encode("ascii"), hashlib.sha256
    ).digest()
    padded = signature + "=" * (-len(signature) % 4)
    assert base64.urlsafe_b64decode(padded) == expected


def test_seeded_fixture_is_explicit_egvv_and_eight_pin() -> None:
    evidence = json.loads(
        (REPO_ROOT / "fixtures" / "acceptance" / "tps5430ddar.egvv.json").read_text()
    )
    spec = json.loads(
        (REPO_ROOT / "fixtures" / "acceptance" / "tps5430ddar.spec.json").read_text()
    )
    assert len(spec["pins"]) == 8
    assert {region["verification"]["method"] for region in evidence["regions"]} == {
        "evidence_gated_visual"
    }
    assert {region["verification"]["score_semantics"] for region in evidence["regions"]} == {
        "calibrated_probability"
    }

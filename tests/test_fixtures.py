"""Fixture integrity tests.

Enforces every rule from docs/CONTRACTS.md §1 that a checked-in fixture must
satisfy. Runs with just the fixture JSON present (the copyright-encumbered
crop bytes are gitignored). When crops are available locally, an extra layer
also cross-checks their sha256 against the JSON. That path is the
canary for "same recipe → same bytes" reproducibility.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "evidence"
SCHEMA_PATH = REPO_ROOT / "scripts" / "schema" / "symbol_evidence_v1.schema.json"
CROP_ROOT = FIXTURE_DIR / "crops"

REQUIRED_REGION_TYPES = ("pinout", "table")


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _list_fixtures() -> list[Path]:
    if not FIXTURE_DIR.is_dir():
        return []
    return sorted(p for p in FIXTURE_DIR.glob("*.json") if p.is_file())


FIXTURES = _list_fixtures()
FIXTURE_IDS = [p.stem for p in FIXTURES]


def _crop_path(fixture: Path, region: dict) -> Path:
    # crop_uri form: dsvire://fixture/<slug>/<region_id>.webp
    return CROP_ROOT / fixture.stem / f"{region['region_id']}.webp"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="session")
def schema() -> dict:
    return _load_schema()


def test_at_least_one_fixture_exists() -> None:
    assert FIXTURES, (
        f"no fixtures found under {FIXTURE_DIR.relative_to(REPO_ROOT)} — "
        "run `python3 scripts/build_fixture.py` to generate them."
    )


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=FIXTURE_IDS)
def test_fixture_validates_against_schema(fixture_path: Path, schema: dict) -> None:
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    jsonschema.validate(doc, schema)


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=FIXTURE_IDS)
def test_bbox_norm_invariants(fixture_path: Path) -> None:
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    for region in doc["regions"]:
        x0, y0, x1, y1 = region["bbox_norm"]
        assert x0 < x1, f"{region['region_id']}: x0 >= x1"
        assert y0 < y1, f"{region['region_id']}: y0 >= y1"


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=FIXTURE_IDS)
def test_required_verified_regions_present(fixture_path: Path) -> None:
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    for required in REQUIRED_REGION_TYPES:
        matches = [
            r for r in doc["regions"]
            if r["type"] == required and r["verified"] is True
        ]
        assert matches, (
            f"{fixture_path.name}: at least one verified region of type "
            f"{required!r} is required by dsvire.symbol-evidence.v1"
        )


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=FIXTURE_IDS)
def test_region_ids_unique(fixture_path: Path) -> None:
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    ids = [r["region_id"] for r in doc["regions"]]
    assert len(ids) == len(set(ids)), f"{fixture_path.name}: duplicate region_id"


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=FIXTURE_IDS)
def test_crop_uri_matches_region_id(fixture_path: Path) -> None:
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    for region in doc["regions"]:
        expected = f"dsvire://fixture/{fixture_path.stem}/{region['region_id']}.webp"
        assert region["crop_uri"] == expected, (
            f"{region['region_id']}: crop_uri {region['crop_uri']} does not "
            f"match convention {expected}"
        )


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=FIXTURE_IDS)
def test_crop_bytes_match_content_hash_when_present(fixture_path: Path) -> None:
    """When the local crop file exists, its sha256 must equal the JSON hash.

    Skipped when crops are absent — the JSON is the source of truth in git;
    crops are regenerated via `scripts/build_fixture.py`.
    """
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    missing_all = all(not _crop_path(fixture_path, r).exists() for r in doc["regions"])
    if missing_all:
        pytest.skip(
            f"no local crops for {fixture_path.stem}; "
            "run `python3 scripts/build_fixture.py` to regenerate"
        )
    for region in doc["regions"]:
        crop = _crop_path(fixture_path, region)
        if not crop.exists():
            pytest.fail(
                f"partial crop set for {fixture_path.stem}: "
                f"{crop.relative_to(REPO_ROOT)} missing while sibling crops exist"
            )
        actual = f"sha256:{_sha256_file(crop)}"
        assert actual == region["content_hash"], (
            f"{region['region_id']}: crop bytes hash {actual} does not match "
            f"fixture {region['content_hash']}. Recipe or encoder version drifted; "
            "rebuild the fixture or bump the recipe."
        )

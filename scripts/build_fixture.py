#!/usr/bin/env python3
"""Build a DS-ViRe evidence-bundle fixture from a real datasheet PDF.

Deterministic pipeline:
    URL -> download (verify sha256) -> pdftoppm render at fixed DPI ->
    Pillow crop by normalized bbox -> WebP lossless encode (fixed method/effort) ->
    sha256 of crop bytes -> emit tokito-dsvire/fixtures/evidence/<mpn>.json

Idempotent: rerunning with the same PDF and the same fixture recipe produces
identical crop bytes and identical JSON (byte-for-byte). Non-determinism (e.g.
different cwebp version) causes the fixture test to fail loudly — that is the
signal the fixture recipe needs a pin bump.

Not a demo runner: this generator only exists so a checked-in JSON fixture can
be reproduced from public bytes without shipping the copyrighted PDF or its
derivative crops in the repo.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "evidence"
CROP_DIR = FIXTURE_DIR / "crops"
SCHEMA_VERSION = "dsvire.symbol-evidence.v2"

# Rendering pins. Bumping either invalidates every committed fixture on purpose.
RENDER_DPI = 300
CWEBP_ARGS = ("-lossless", "-z", "9", "-m", "6", "-quiet")


# ---------------------------------------------------------------------------
# Recipe types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RegionRecipe:
    region_id: str
    type: str
    page: int
    bbox_norm: tuple[float, float, float, float]
    verification_score: float
    caption: str | None = None

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.bbox_norm
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            raise ValueError(f"invalid bbox_norm for {self.region_id}: {self.bbox_norm}")
        if not (0.0 <= self.verification_score <= 1.0):
            raise ValueError(f"invalid verification_score for {self.region_id}")


@dataclasses.dataclass(frozen=True)
class DatasheetRecipe:
    id: str
    url: str
    content_sha256: str
    manufacturer: str
    mpn: str
    package: str


@dataclasses.dataclass(frozen=True)
class FixtureRecipe:
    slug: str  # filesystem-safe, becomes <slug>.json
    datasheet: DatasheetRecipe
    regions: Sequence[RegionRecipe]
    index_version: str
    model_ids: Sequence[str]
    query_ids: Sequence[str]


# ---------------------------------------------------------------------------
# Recipes (one entry per fixture the repo maintains)
# ---------------------------------------------------------------------------

TPS5430DDAR = FixtureRecipe(
    slug="tps5430ddar",
    datasheet=DatasheetRecipe(
        id="ti-slvs632l",
        url="https://www.ti.com/lit/ds/symlink/tps5430.pdf",
        content_sha256="83074fc1265c8e5c6639511bdb9f83e96c6e6f993613deadea0d09c3a12a2c07",
        manufacturer="Texas Instruments",
        mpn="TPS5430DDAR",
        package="SO-PowerPAD-8",
    ),
    regions=(
        RegionRecipe(
            region_id="r_pinout_01",
            type="pinout",
            page=3,
            # Page 3 (Pin Configuration and Functions). Figure 4-1 sits at
            # (140,100)->(475,260) in 612x792 PDF points. Normalized:
            bbox_norm=(0.229, 0.126, 0.776, 0.328),
            verification_score=0.97,
            caption="Figure 4-1. DDA Package 8-Pin HSOIC With Thermal Pad (Top View)",
        ),
        RegionRecipe(
            region_id="r_pin_table_01",
            type="table",
            page=3,
            # Table 4-1 (Pin Functions), including caption and the (1) footnote.
            bbox_norm=(0.065, 0.328, 0.935, 0.600),
            verification_score=0.94,
            caption="Table 4-1. Pin Functions",
        ),
        RegionRecipe(
            region_id="r_package_01",
            type="package",
            page=3,
            bbox_norm=(0.229, 0.126, 0.776, 0.328),
            verification_score=1.0,
            caption="DDA package identity and top-view pinout",
        ),
    ),
    index_version="fixture@1",
    model_ids=("fixture",),
    query_ids=("q_pinout", "q_pin_table"),
)

RECIPES: dict[str, FixtureRecipe] = {
    TPS5430DDAR.slug: TPS5430DDAR,
}


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_pdf(url: str, expected_sha256: str, cache_dir: Path) -> Path:
    """Download the PDF (cached by expected hash) and verify."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{expected_sha256}.pdf"
    if not dest.exists():
        tmp = dest.with_suffix(".pdf.part")
        subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--location", "--output", str(tmp), url],
            check=True,
        )
        got = sha256_file(tmp)
        if got != expected_sha256:
            tmp.unlink()
            raise RuntimeError(
                f"downloaded {url} has sha256 {got}, recipe expects {expected_sha256}. "
                "Upstream datasheet has been re-published — bump the recipe or pin an "
                "archived copy."
            )
        tmp.rename(dest)
    else:
        got = sha256_file(dest)
        if got != expected_sha256:
            raise RuntimeError(f"cached PDF {dest} has sha256 {got}, expected {expected_sha256}")
    return dest


def render_page(pdf: Path, page: int, dpi: int, out_dir: Path) -> Path:
    """Render one PDF page to PNG via pdftoppm at a fixed DPI."""
    prefix = out_dir / f"p{page:04d}"
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(dpi),
            "-f",
            str(page),
            "-l",
            str(page),
            "-png",
            str(pdf),
            str(prefix),
        ],
        check=True,
    )
    # pdftoppm emits <prefix>-<page>.png with variable zero-padding across
    # versions; glob to be safe.
    matches = sorted(out_dir.glob(f"{prefix.name}-*.png"))
    if not matches:
        raise RuntimeError(f"pdftoppm produced no output for {pdf} page {page}")
    return matches[0]


def crop_region(page_png: Path, bbox_norm: tuple[float, float, float, float], dest: Path) -> None:
    """Crop by normalized bbox, encode as lossless WebP via cwebp for determinism."""
    with Image.open(page_png) as img:
        w, h = img.size
        x0, y0, x1, y1 = bbox_norm
        # Round inward to keep the crop inside the page pixel grid.
        px = (
            round(x0 * w),
            round(y0 * h),
            round(x1 * w),
            round(y1 * h),
        )
        crop = img.crop(px)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_png = Path(tf.name)
    try:
        # PIL PNG output is deterministic; feed the same bytes to cwebp each run.
        crop.save(tmp_png, format="PNG", optimize=False, compress_level=9)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["cwebp", *CWEBP_ARGS, str(tmp_png), "-o", str(dest)],
            check=True,
        )
    finally:
        tmp_png.unlink(missing_ok=True)


def crop_uri(mpn_slug: str, region_id: str) -> str:
    """dsvire:// URI scheme for a fixture-hosted crop."""
    return f"dsvire://fixture/{mpn_slug}/{region_id}.webp"


def build_fixture(recipe: FixtureRecipe, cache_dir: Path) -> dict:
    pdf = download_pdf(recipe.datasheet.url, recipe.datasheet.content_sha256, cache_dir)
    with tempfile.TemporaryDirectory() as raw:
        raw_dir = Path(raw)
        # Group crops by page to render each page exactly once.
        pages_needed = sorted({r.page for r in recipe.regions})
        page_pngs = {p: render_page(pdf, p, RENDER_DPI, raw_dir) for p in pages_needed}

        regions_out = []
        for r in recipe.regions:
            crop_path = CROP_DIR / recipe.slug / f"{r.region_id}.webp"
            crop_region(page_pngs[r.page], r.bbox_norm, crop_path)
            region_json: dict = {
                "region_id": r.region_id,
                "type": r.type,
                "page": r.page,
                "bbox_norm": list(r.bbox_norm),
                "crop_uri": crop_uri(recipe.slug, r.region_id),
                "content_hash": f"sha256:{sha256_file(crop_path)}",
                "verification": {
                    "method": "text_layout_heuristic",
                    "policy_version": "fixture.text-layout@1.0.0",
                    "outcome": "accepted",
                    "score": r.verification_score,
                    "score_semantics": "heuristic_evidence_strength",
                },
            }
            if r.caption is not None:
                region_json["caption"] = r.caption
            regions_out.append(region_json)

    return {
        "schema_version": SCHEMA_VERSION,
        "datasheet": {
            "id": recipe.datasheet.id,
            "content_sha256": recipe.datasheet.content_sha256,
            "manufacturer": recipe.datasheet.manufacturer,
            "mpn": recipe.datasheet.mpn,
            "package": recipe.datasheet.package,
        },
        "identity_verification": {
            "method": "exact_text_orderable_part",
            "policy_version": "fixture.identity-text@1.0.0",
            "outcome": "accepted",
            "manufacturer_observed": True,
            "exact_mpn_observed": True,
            "package_associated": True,
            "evidence_region_ids": ["r_package_01"],
        },
        "regions": regions_out,
        "retrieval": {
            "index_version": recipe.index_version,
            "model_ids": list(recipe.model_ids),
            "query_ids": list(recipe.query_ids),
        },
    }


def write_json(fixture: dict, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic serialization: sort_keys=False (spec has a fixed field order),
    # trailing newline, indent=2, LF line endings, no whitespace jitter.
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    dest.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "slugs",
        nargs="*",
        default=list(RECIPES.keys()),
        help="fixture slugs to build (default: all recipes)",
    )
    ap.add_argument(
        "--cache",
        type=Path,
        default=REPO_ROOT / ".cache" / "datasheets",
        help="PDF cache dir (default: <repo>/.cache/datasheets)",
    )
    args = ap.parse_args()

    unknown = [s for s in args.slugs if s not in RECIPES]
    if unknown:
        print(f"unknown fixture slugs: {unknown}", file=sys.stderr)
        return 2

    for slug in args.slugs:
        recipe = RECIPES[slug]
        print(f"[{slug}] building...", flush=True)
        fixture = build_fixture(recipe, args.cache)
        dest = FIXTURE_DIR / f"{slug}.json"
        write_json(fixture, dest)
        print(f"[{slug}] wrote {dest.relative_to(REPO_ROOT)}", flush=True)
        for region in fixture["regions"]:
            print(f"  {region['region_id']:20s} {region['content_hash']}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

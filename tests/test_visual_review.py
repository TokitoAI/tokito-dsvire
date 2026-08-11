from __future__ import annotations

import hashlib
from io import BytesIO

import pytest

from dsvire.visual_adapters import AdapterError
from dsvire.visual_registry import load_visual_registry_data
from dsvire.visual_review import render_review_sheet, review_sheet_filename


def _fixture() -> tuple[bytes, object]:
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "ACME A-1 SOIC-8 Pin Configuration Top View Pin Functions")
    payload = document.tobytes()
    document.close()
    identity = {"manufacturer": "ACME", "mpn": "A-1", "package": "SOIC-8"}

    def case(
        case_id: str,
        label: str,
        region: str,
        claimed: dict[str, str] | None = None,
        view: str = "not_applicable",
    ) -> dict[str, object]:
        return {
            "id": case_id,
            "label": label,
            "region_type": region,
            "page": 1,
            "bbox_norm": [0.0, 0.0, 1.0, 1.0],
            "view": view,
            "claimed_identity": claimed or identity,
            "rationale": "Synthetic review fixture.",
        }

    registry = load_visual_registry_data(
        {
            "schema_version": "dsvire.visual-eval-registry.v1",
            "documents": [
                {
                    "id": "../acme/a-1",
                    "document_group": "acme-a",
                    "split": "development",
                    "category": "test",
                    "source": {"url": "https://example.invalid/a.pdf", "revision": "test"},
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "redistribution": "redistributable",
                    "license_note": "Synthetic.",
                    "identity": identity,
                    "review": {
                        "status": "unreviewed",
                        "reviewers": [],
                        "reviewed_at": None,
                        "annotation_revision": "fixture@1",
                    },
                    "cases": [
                        case("pin", "positive", "pinout", view="top"),
                        case("table", "positive", "table"),
                        case("package", "positive", "package"),
                        case("wrong-view", "wrong_view", "pinout", view="bottom"),
                    ],
                }
            ],
        }
    )
    return payload, registry.documents[0]


def test_review_sheet_is_png_and_labels_every_case() -> None:
    image_module = pytest.importorskip("PIL.Image")
    payload, document = _fixture()
    rendered = render_review_sheet(payload, document)
    with image_module.open(BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == (1880, 1400)


def test_review_sheet_rejects_unpinned_bytes() -> None:
    _payload, document = _fixture()
    with pytest.raises(AdapterError, match="SHA-256 mismatch"):
        render_review_sheet(b"not the pinned PDF", document)


def test_review_sheet_filename_cannot_escape_output_directory() -> None:
    filename = review_sheet_filename("../../sensitive\\name")
    assert "/" not in filename and "\\" not in filename and ".." not in filename
    assert filename.endswith(".png")

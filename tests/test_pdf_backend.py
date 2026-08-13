from __future__ import annotations

import io

import pytest
from PIL import Image

from dsvire.pdf_backend import PdfBackendError, PdfDocument
from dsvire.pdf_fixtures import text_pdf


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_pages_have_bounded_geometry_and_render(rotation: int) -> None:
    payload = text_pdf(["ROTATION SENTINEL"], sizes=[(320, 480)], rotations=[rotation])
    with PdfDocument(payload) as document, document.load_page(0) as page:
        assert "ROTATION SENTINEL" in page.text()
        assert page.blocks()
        for block in page.blocks():
            x0, y0, x1, y1 = block.bbox
            assert 0 <= x0 < x1 <= page.rect.width
            assert 0 <= y0 < y1 <= page.rect.height
        rendered = page.render_png((0, 0, page.rect.width, page.rect.height), dpi=72)
    with Image.open(io.BytesIO(rendered)) as image:
        assert image.mode == "RGB"
        assert image.width > 0 and image.height > 0


@pytest.mark.parametrize(
    "bbox,error",
    [
        ((-1.0, 0.0, 10.0, 10.0), "outside"),
        ((0.0, 0.0, 10_000.0, 10.0), "outside"),
        ((1.0, 1.0, 1.0, 2.0), "positive area"),
        ((0.0, 0.0, float("nan"), 2.0), "finite"),
    ],
)
def test_crop_validation_fails_closed(bbox: tuple[float, float, float, float], error: str) -> None:
    with (
        PdfDocument(text_pdf(["bounded"])) as document,
        document.load_page(0) as page,
        pytest.raises(PdfBackendError, match=error),
    ):
        page.render_png(bbox, dpi=72)


@pytest.mark.parametrize("dpi", [0, 35, 601, 72.5])
def test_render_dpi_is_bounded(dpi: object) -> None:
    with (
        PdfDocument(text_pdf(["bounded"])) as document,
        document.load_page(0) as page,
        pytest.raises(PdfBackendError, match="DPI"),
    ):
        page.render_png((0, 0, page.rect.width, page.rect.height), dpi=dpi)  # type: ignore[arg-type]


def test_document_cannot_be_used_after_close() -> None:
    document = PdfDocument(text_pdf(["closed"]))
    document.close()
    assert document.page_count == 0
    with pytest.raises(PdfBackendError, match="closed"):
        document.load_page(0)

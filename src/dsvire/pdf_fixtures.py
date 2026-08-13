"""Deterministic pure-pypdf generators for tests and robustness campaigns."""

from __future__ import annotations

import io
from collections.abc import Sequence

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)


def _pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def add_text_page(
    writer: PdfWriter,
    text: str,
    *,
    width: float = 595,
    height: float = 842,
    rotation: int = 0,
) -> None:
    page = writer.add_blank_page(width=width, height=height)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    commands = ["BT", "/F1 11 Tf", "14 TL", f"72 {height - 72} Td"]
    for index, line in enumerate(text.splitlines() or [""]):
        if index:
            commands.append("T*")
        commands.append(f"({_pdf_text(line)}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data(("\n".join(commands) + "\n").encode("latin-1", errors="replace"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotation:
        page[NameObject("/Rotate")] = NumberObject(rotation)


def add_rgb_image_page(
    writer: PdfWriter,
    rgb: bytes,
    *,
    width: int,
    height: int,
) -> None:
    if len(rgb) != width * height * 3:
        raise ValueError("RGB fixture byte count does not match dimensions")
    page = writer.add_blank_page(width=width, height=height)
    image = DecodedStreamObject()
    image.set_data(rgb)
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_ref = writer._add_object(image)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"q\n{width} 0 0 {height} 0 0 cm\n/Im0 Do\nQ\n".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)


def write_pdf(writer: PdfWriter) -> bytes:
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def text_pdf(
    pages: Sequence[str],
    *,
    sizes: Sequence[tuple[float, float]] | None = None,
    rotations: Sequence[int] | None = None,
) -> bytes:
    writer = PdfWriter()
    for index, text in enumerate(pages):
        width, height = sizes[index] if sizes is not None else (595, 842)
        rotation = rotations[index] if rotations is not None else 0
        add_text_page(writer, text, width=width, height=height, rotation=rotation)
    return write_pdf(writer)

"""Shared test fixtures + a synthetic PDF generator for offline golden tests."""

from __future__ import annotations

from io import BytesIO

import pytest


@pytest.fixture(scope="session")
def synthetic_pdf_bytes() -> bytes:
    """A small multi-page PDF built in-memory (no fixtures on disk needed)."""
    import pypdfium2 as _  # noqa: F401  (ensures the rasterizer dep is importable)
    from PIL import Image
    from pypdf import PdfWriter

    # Build pages from images via img2pdf-free path: render PIL -> PDF using Pillow.
    pages = []
    for i in range(3):
        img = Image.new("RGB", (1240, 1754), (255, 255, 255))
        # crude text-like blocks so rasterization has content
        for y in range(100, 1600, 60):
            for x in range(80, 1100, 8):
                if (x // 8 + y) % 3 == 0:
                    img.putpixel((x, y), (10 + i * 20, 10, 10))
        pages.append(img)

    buf = BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    pdf_bytes = buf.getvalue()

    # round-trip through pypdf to guarantee a clean, multi-page PDF
    reader_buf = BytesIO(pdf_bytes)
    from pypdf import PdfReader

    reader = PdfReader(reader_buf)
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture()
def synthetic_pdf(tmp_path, synthetic_pdf_bytes) -> str:
    path = tmp_path / "sample.pdf"
    path.write_bytes(synthetic_pdf_bytes)
    return str(path)


@pytest.fixture()
def large_image():
    """A high-resolution image that will exceed small base64 caps."""
    from PIL import Image

    img = Image.new("RGB", (4000, 4000))
    # noise so JPEG can't trivially compress it to nothing
    import random

    random.seed(0)
    px = img.load()
    for x in range(0, 4000, 2):
        for y in range(0, 4000, 2):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    return img

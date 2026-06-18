"""PDF utilities — reused from superclaims-ai ``utils/pdf.py`` and extended.

``extract_pages_as_base64`` keeps the original page-range contract (used by the Gemini
PDF-native path). ``pdf_to_images`` is the new sibling for non-PDF-native providers
(Grok et al.) — it rasterizes each page to a PIL image via PyMuPDF (primary) with a
pypdfium2 fallback, so the doc-prep toolkit has no hard system dependency on either.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image


def extract_pages_as_base64(file_path: str, page_ranges: str | None = None) -> str:
    """Return base64-encoded PDF bytes for selected 1-based pages.

    If ``page_ranges`` is falsy, the whole PDF is returned. If extraction fails for any
    reason the original PDF is returned, preserving robustness (mirrors superclaims-ai).
    """
    path = Path(file_path)
    raw_pdf = path.read_bytes()
    if not page_ranges:
        return base64.b64encode(raw_pdf).decode("utf-8")

    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(BytesIO(raw_pdf))
        writer = PdfWriter()
        for page_number in expand_page_ranges(page_ranges, len(reader.pages)):
            writer.add_page(reader.pages[page_number - 1])
        if len(writer.pages) == 0:
            return base64.b64encode(raw_pdf).decode("utf-8")
        output = BytesIO()
        writer.write(output)
        return base64.b64encode(output.getvalue()).decode("utf-8")
    except Exception:
        return base64.b64encode(raw_pdf).decode("utf-8")


def select_pages(file_path: str, page_ranges: str) -> bytes:
    """Return PDF bytes containing only the selected 1-based pages (round-trips structure)."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(file_path))
    writer = PdfWriter()
    for page_number in expand_page_ranges(page_ranges, len(reader.pages)):
        writer.add_page(reader.pages[page_number - 1])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def merge_pdfs(file_paths: list[str | Path]) -> bytes:
    """Merge several PDFs into one packet, preserving page order."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for fp in file_paths:
        reader = PdfReader(str(fp))
        for page in reader.pages:
            writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def page_count(file_path: str | Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(file_path)).pages)


def pdf_to_images(file_path: str | Path, *, dpi: int = 150) -> list[Image.Image]:
    """Rasterize each PDF page to a PIL image. PyMuPDF primary, pypdfium2 fallback.

    Used by non-PDF-native providers (e.g. Grok) where pages must be sent as images.
    """
    path = str(file_path)
    try:
        return _pdf_to_images_pymupdf(path, dpi=dpi)
    except Exception:
        return _pdf_to_images_pdfium(path, dpi=dpi)


def _pdf_to_images_pymupdf(path: str, *, dpi: int) -> list[Image.Image]:
    import fitz  # PyMuPDF

    images: list[Image.Image] = []
    doc = fitz.open(path)
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    finally:
        doc.close()
    return images


def _pdf_to_images_pdfium(path: str, *, dpi: int) -> list[Image.Image]:
    import pypdfium2 as pdfium

    scale = dpi / 72.0
    pdf = pdfium.PdfDocument(path)
    try:
        images: list[Image.Image] = []
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            images.append(bitmap.to_pil().convert("RGB"))
        return images
    finally:
        pdf.close()


def expand_page_ranges(page_ranges: str, max_pages: int) -> list[int]:
    """Expand ``"1,3-5"`` into ``[1, 3, 4, 5]`` (1-based, clamped to ``max_pages``)."""
    pages: set[int] = set()
    for part in page_ranges.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            pages.update(range(int(start_text.strip()), int(end_text.strip()) + 1))
        else:
            pages.add(int(token))
    return sorted(p for p in pages if 1 <= p <= max_pages)

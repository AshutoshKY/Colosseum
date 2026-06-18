"""Document-prep golden tests (must pass offline, no network/creds).

Covers the capability-gap requirement from docs/plan.md:
* PDF -> images rasterizes under each provider cap (4 MB Grok / 30 MB Vertex);
* page select/merge round-trips;
* an oversized image compresses under the limit;
* mime/format conversion (jpg/png) is correct;
* base64 size accounting matches what the API counts.
"""

from __future__ import annotations

import base64

import pytest
from app.providers.docprep import (
    base64_size_bytes,
    base64_size_mb,
    encode_image,
    megapixels,
    prepare_image_for_cap,
)
from app.utils.pdf import (
    expand_page_ranges,
    merge_pdfs,
    page_count,
    pdf_to_images,
    select_pages,
)

GROK_CAP_MB = 4.0
VERTEX_CAP_MB = 30.0


# --------------------------------------------------------------------------- base64 accounting
def test_base64_size_accounting_matches_api_count():
    raw = b"\x00\x01\x02" * 5000
    encoded = base64.b64encode(raw)
    assert base64_size_bytes(raw) == len(encoded)
    # base64 inflates by ~4/3
    assert base64_size_bytes(raw) > len(raw)
    assert abs(base64_size_mb(raw) - len(encoded) / (1024 * 1024)) < 1e-9


# --------------------------------------------------------------------------- PDF -> images
def test_pdf_to_images_under_each_provider_cap(synthetic_pdf):
    images = pdf_to_images(synthetic_pdf, dpi=150)
    assert len(images) == 3
    for img in images:
        prepared = prepare_image_for_cap(img, max_mb=GROK_CAP_MB, max_megapixels=33.0, fmt="jpeg")
        assert prepared.base64_mb <= GROK_CAP_MB
        assert prepared.mime_type == "image/jpeg"
        # also comfortably under the larger Vertex cap
        assert prepared.base64_mb <= VERTEX_CAP_MB


# --------------------------------------------------------------------------- page select / merge
def test_select_pages_round_trip(synthetic_pdf):
    selected = select_pages(synthetic_pdf, "1,3")
    import tempfile
    from pathlib import Path

    out = Path(tempfile.mkstemp(suffix=".pdf")[1])
    out.write_bytes(selected)
    assert page_count(out) == 2


def test_merge_pdfs_round_trip(synthetic_pdf):
    merged = merge_pdfs([synthetic_pdf, synthetic_pdf])
    import tempfile
    from pathlib import Path

    out = Path(tempfile.mkstemp(suffix=".pdf")[1])
    out.write_bytes(merged)
    assert page_count(out) == 6  # 3 + 3


def test_expand_page_ranges():
    assert expand_page_ranges("1,3-5", 10) == [1, 3, 4, 5]
    assert expand_page_ranges("1,3-5", 4) == [1, 3, 4]  # clamped
    assert expand_page_ranges("", 10) == []


# --------------------------------------------------------------------------- compression to cap
def test_oversized_image_compresses_under_grok_cap(large_image):
    # raw PNG of a 4000x4000 noisy image is far over 4 MB base64
    raw_png = encode_image(large_image, fmt="png")
    assert base64_size_mb(raw_png) > GROK_CAP_MB

    prepared = prepare_image_for_cap(
        large_image, max_mb=GROK_CAP_MB, max_megapixels=33.0, fmt="jpeg"
    )
    assert prepared.base64_mb <= GROK_CAP_MB
    assert prepared.original_base64_mb >= prepared.base64_mb


def test_megapixel_cap_enforced():
    from PIL import Image

    # 7000x7000 = 49 MP, over Grok's ~33 MP
    img = Image.new("RGB", (7000, 7000), (128, 128, 128))
    assert megapixels(img) > 33.0
    prepared = prepare_image_for_cap(img, max_mb=GROK_CAP_MB, max_megapixels=33.0, fmt="jpeg")
    out_mp = (prepared.width * prepared.height) / 1_000_000
    assert out_mp <= 33.0 + 1e-6


# --------------------------------------------------------------------------- mime / format
def test_format_conversion_mime_correct():
    from PIL import Image

    img = Image.new("RGB", (200, 200), (255, 0, 0))
    jpeg = prepare_image_for_cap(img, max_mb=None, fmt="jpeg")
    png = prepare_image_for_cap(img, max_mb=None, fmt="png")
    assert jpeg.mime_type == "image/jpeg"
    assert png.mime_type == "image/png"
    # magic bytes
    assert jpeg.data[:3] == b"\xff\xd8\xff"  # JPEG SOI
    assert png.data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature


def test_unsupported_format_rejected():
    from PIL import Image

    with pytest.raises(ValueError):
        prepare_image_for_cap(Image.new("RGB", (10, 10)), max_mb=None, fmt="gif")

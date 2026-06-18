"""Document-prep toolkit — image compression / resize / base64-size accounting.

The hard per-model caveats (Grok base64 <=4 MB, <=33 MP, jpg/png only; Vertex 30 MB total
payload) are enforced here. Adapters call ``prepare_image_for_cap`` to bring each rasterized
page under a model's per-image cap, and ``base64_size_mb`` to measure what the API actually
counts (base64-encoded bytes, not raw bytes).

Golden tests live in ``backend/tests/test_docprep.py``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

# base64 inflates bytes by ~4/3 (plus padding). The API counts the encoded size.
_BASE64_OVERHEAD = 4 / 3


def encode_image(image: Image.Image, *, fmt: str = "JPEG", quality: int = 90) -> bytes:
    """Encode a PIL image to raw bytes in the requested format."""
    fmt_norm = _normalize_format(fmt)
    buf = BytesIO()
    save_kwargs: dict[str, object] = {}
    if fmt_norm == "JPEG":
        save_kwargs.update(quality=quality, optimize=True)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
    image.save(buf, format=fmt_norm, **save_kwargs)
    return buf.getvalue()


def base64_size_bytes(raw: bytes) -> int:
    """Exact size of ``raw`` once base64-encoded (what the API counts)."""
    return len(base64.b64encode(raw))


def base64_size_mb(raw: bytes) -> float:
    return base64_size_bytes(raw) / (1024 * 1024)


def to_base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def megapixels(image: Image.Image) -> float:
    return (image.width * image.height) / 1_000_000


@dataclass(frozen=True)
class PreparedImage:
    """A rasterized page made compliant with a model's image caps."""

    data: bytes
    base64: str
    mime_type: str
    width: int
    height: int
    base64_mb: float
    original_base64_mb: float


def prepare_image_for_cap(
    image: Image.Image,
    *,
    max_mb: float | None,
    max_megapixels: float | None = None,
    fmt: str = "jpeg",
    min_quality: int = 35,
    min_dimension: int = 256,
) -> PreparedImage:
    """Bring ``image`` under ``max_mb`` (base64) and ``max_megapixels`` for the given format.

    Strategy: first cap resolution (megapixels), then iteratively reduce JPEG quality, then
    downscale, until the *base64-encoded* size is under ``max_mb``. PNG (lossless) only
    downscales. Returns the compliant bytes + accurate base64 size accounting.
    """
    fmt_norm = _normalize_format(fmt)
    mime = "image/png" if fmt_norm == "PNG" else "image/jpeg"

    work = image.convert("RGB") if fmt_norm == "JPEG" and image.mode not in ("RGB", "L") else image

    # 1. enforce resolution cap (megapixels), e.g. Grok ~33 MP.
    if max_megapixels is not None and megapixels(work) > max_megapixels:
        work = _resize_to_megapixels(work, max_megapixels)

    original_raw = encode_image(work, fmt=fmt_norm, quality=95)
    original_mb = base64_size_mb(original_raw)

    if max_mb is None or original_mb <= max_mb:
        return PreparedImage(
            data=original_raw,
            base64=to_base64(original_raw),
            mime_type=mime,
            width=work.width,
            height=work.height,
            base64_mb=original_mb,
            original_base64_mb=original_mb,
        )

    quality = 90
    current = work
    raw = original_raw
    # 2. quality + downscale loop.
    for _ in range(40):
        raw = encode_image(current, fmt=fmt_norm, quality=quality)
        if base64_size_mb(raw) <= max_mb:
            break
        if fmt_norm == "JPEG" and quality > min_quality:
            quality = max(min_quality, quality - 10)
            continue
        # downscale 15% each step (lossless formats land here immediately).
        new_w = int(current.width * 0.85)
        new_h = int(current.height * 0.85)
        if new_w < min_dimension or new_h < min_dimension:
            break
        current = current.resize((new_w, new_h), Image.LANCZOS)
        quality = 90 if fmt_norm == "JPEG" else quality

    return PreparedImage(
        data=raw,
        base64=to_base64(raw),
        mime_type=mime,
        width=current.width,
        height=current.height,
        base64_mb=base64_size_mb(raw),
        original_base64_mb=original_mb,
    )


def estimate_base64_mb_for_payload(parts: list[bytes]) -> float:
    """Total base64-encoded size (MB) of several raw byte parts (for the payload cap check)."""
    return sum(base64_size_mb(p) for p in parts)


def _resize_to_megapixels(image: Image.Image, max_mp: float) -> Image.Image:
    current_mp = megapixels(image)
    if current_mp <= max_mp:
        return image
    factor = (max_mp / current_mp) ** 0.5
    new_w = max(1, int(image.width * factor))
    new_h = max(1, int(image.height * factor))
    return image.resize((new_w, new_h), Image.LANCZOS)


def _normalize_format(fmt: str) -> str:
    f = fmt.strip().lower()
    if f in ("jpg", "jpeg"):
        return "JPEG"
    if f == "png":
        return "PNG"
    raise ValueError(f"Unsupported image format: {fmt!r} (use jpeg/png)")

"""Rasterizing adapter for non-PDF-native providers.

Used by ``vertex_partner`` (Grok/Llama/Gemma/Mistral vision MaaS), ``xai`` (Grok direct), and
``openai_compatible`` (GLM-V/Kimi external) models that accept images but NOT native PDF. It
rasterizes each requested PDF page to an image via ``pdf_to_images`` (PyMuPDF primary, pdfium
fallback) and brings each page under the model's per-image cap (Grok 4 MB base64, <=33 MP,
jpg/png only) via the Phase-1 ``prepare_image_for_cap`` doc-prep toolkit. It also accounts the
total base64 payload against the Vertex 30 MB cap.

Capability gates (shared base ``gate``):
* text-only model on an image/PDF task -> ``CapabilityGateError`` -> recorded "not applicable".
* a model with vision but no pdf_native is allowed: pages become images here.
"""

from __future__ import annotations

from app.providers.adapters.base import (
    DocumentInput,
    NormalizedContent,
    ProviderAdapter,
    _assert_exists,
)
from app.providers.docprep import base64_size_mb, prepare_image_for_cap
from app.utils.pdf import pdf_to_images


class RasterizingAdapter(ProviderAdapter):
    """Rasterize PDF pages -> compliant images for vision-but-not-PDF-native models."""

    def normalize(
        self, *, system: str, instruction: str, documents: list[DocumentInput]
    ) -> NormalizedContent:
        self.gate(documents)
        cap = self.capability

        content: list[dict[str, object]] = [{"type": "text", "text": instruction}]
        image_count = 0
        total_b64_mb = 0.0
        # Pick the single accepted raster format (jpeg preferred where allowed).
        fmt = "jpeg" if "jpeg" in cap.image_formats else next(iter(cap.image_formats), "png")

        for doc in documents:
            _assert_exists(doc.path)
            images = pdf_to_images(doc.path)
            # Honor requested page ranges (1-based) so we don't blow the payload cap.
            if doc.page_ranges:
                from app.utils.pdf import expand_page_ranges

                wanted = expand_page_ranges(doc.page_ranges, len(images))
                images = [images[p - 1] for p in wanted]

            for img in images:
                prepared = prepare_image_for_cap(
                    img,
                    max_mb=cap.max_image_mb,
                    max_megapixels=cap.max_image_megapixels,
                    fmt=fmt,
                )
                total_b64_mb += base64_size_mb(prepared.data)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{prepared.mime_type};base64,{prepared.base64}"
                        },
                    }
                )
                image_count += 1

        notes: dict[str, object] = {
            "raster_format": fmt,
            "max_image_mb": cap.max_image_mb,
            "max_image_megapixels": cap.max_image_megapixels,
            "payload_cap_mb": cap.max_payload_mb,
        }
        if cap.max_payload_mb is not None and total_b64_mb > cap.max_payload_mb:
            notes["over_payload_cap"] = True
            notes["hint"] = "select fewer pages (page_ranges) to fit under the cap"

        return NormalizedContent(
            system=system,
            content=content,
            transport="rasterized_images",
            image_count=image_count,
            sent_payload_mb=round(total_b64_mb, 4),
            notes=notes,
        )

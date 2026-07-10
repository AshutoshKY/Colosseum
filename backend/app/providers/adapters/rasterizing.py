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

# Vision-token accounting for ViT-style encoders (Qwen3-VL et al.): a 14px patch merged 2x2
# gives one token per ~28x28px block, i.e. tokens ~= megapixels * 1e6 / (28*28) ~= mp * 1276.
_TOKENS_PER_MEGAPIXEL = 1_000_000 / (28 * 28)
# Reserve headroom in the context window for the text instruction + the model's output.
_CONTEXT_RESERVE_TOKENS = 3000
# Never downscale a page below this — past it OCR/layout becomes unreadable and the run is moot.
_MIN_PAGE_MEGAPIXELS = 0.5


class RasterizingAdapter(ProviderAdapter):
    """Rasterize PDF pages -> compliant images for vision-but-not-PDF-native models."""

    def _context_budget_megapixels(self, page_count: int) -> float | None:
        """Per-page megapixel cap so all pages' vision tokens fit the model's context window.

        Returns ``None`` when the model has no declared ``context_window`` (no budget to enforce)
        or has no pages. Otherwise splits the usable token budget evenly across pages and
        converts to megapixels, floored at ``_MIN_PAGE_MEGAPIXELS`` so pages stay legible (a
        very long packet may still exceed the window at that floor — better a readable
        best-effort than an unusable one).
        """
        window = self.capability.context_window
        if not window or page_count <= 0:
            return None
        usable = max(window - _CONTEXT_RESERVE_TOKENS, _CONTEXT_RESERVE_TOKENS)
        per_page_tokens = usable / page_count
        per_page_mp = per_page_tokens / _TOKENS_PER_MEGAPIXEL
        return max(per_page_mp, _MIN_PAGE_MEGAPIXELS)

    def normalize(
        self,
        *,
        system: str,
        instruction: str,
        documents: list[DocumentInput],
        config: dict[str, object] | None = None,
    ) -> NormalizedContent:
        self.gate(documents)
        cap = self.capability

        # Effective caps: always honor the per-model catalog caps; when the run enables
        # compression, tighten to the smaller of the catalog cap and the requested budget so
        # rasterized pages fit the model's context window.
        max_megapixels = cap.max_image_megapixels
        max_image_mb = cap.max_image_mb
        compression = (config or {}).get("compression")
        if isinstance(compression, dict) and compression.get("enabled"):
            requested_mp = compression.get("max_megapixels")
            if requested_mp is not None:
                max_megapixels = min(x for x in (max_megapixels, requested_mp) if x is not None)
            requested_mb = compression.get("max_image_mb")
            if requested_mb is not None:
                max_image_mb = min(x for x in (max_image_mb, requested_mb) if x is not None)

        content: list[dict[str, object]] = [{"type": "text", "text": instruction}]
        total_b64_mb = 0.0
        # Pick the single accepted raster format (jpeg preferred where allowed).
        fmt = "jpeg" if "jpeg" in cap.image_formats else next(iter(cap.image_formats), "png")

        # Gather every page first so we can budget the *combined* vision-token count against the
        # model's context window — the per-image MP cap bounds one page, but a multi-page packet
        # sums up and can exceed a small window (e.g. Qwen3-VL max_model_len 26032) even when
        # each page individually fits. See _fit_context_budget.
        all_images = []
        for doc in documents:
            _assert_exists(doc.path)
            images = pdf_to_images(doc.path)
            # Honor requested page ranges (1-based) so we don't blow the payload cap.
            if doc.page_ranges:
                from app.utils.pdf import expand_page_ranges

                wanted = expand_page_ranges(doc.page_ranges, len(images))
                images = [images[p - 1] for p in wanted]
            all_images.extend(images)

        context_mp = self._context_budget_megapixels(len(all_images))
        if context_mp is not None:
            max_megapixels = min(x for x in (max_megapixels, context_mp) if x is not None)

        for img in all_images:
            prepared = prepare_image_for_cap(
                img,
                max_mb=max_image_mb,
                max_megapixels=max_megapixels,
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
        image_count = len(all_images)

        notes: dict[str, object] = {
            "raster_format": fmt,
            "max_image_mb": max_image_mb,
            "max_image_megapixels": max_megapixels,
            "context_budget_megapixels": context_mp,
            "payload_cap_mb": cap.max_payload_mb,
            "compressed": bool(
                isinstance(compression, dict) and compression.get("enabled")
            ),
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

"""Gemini-on-Vertex adapter — PDF native pass-through.

Gemini ingests PDF directly as a file part. We mirror the shape used by superclaims-ai
(``{"type": "file", "mime_type": "application/pdf", ...}``) but emit the OpenAI-style content
blocks LiteLLM expects (``image_url`` with a ``data:`` URI also works for PDFs on the Vertex
route via LiteLLM's ``file`` content type). We honor Vertex's 30 MB payload cap by measuring
the base64-encoded size of what we send and selecting only the requested pages.
"""

from __future__ import annotations

from app.providers.adapters.base import (
    DocumentInput,
    NormalizedContent,
    ProviderAdapter,
    _assert_exists,
)
from app.providers.docprep import base64_size_mb


class GeminiVertexAdapter(ProviderAdapter):
    """Pass PDFs through natively; no rasterization."""

    def normalize(
        self,
        *,
        system: str,
        instruction: str,
        documents: list[DocumentInput],
        config: dict[str, object] | None = None,
    ) -> NormalizedContent:
        del config  # PDF-native pass-through; image compression does not apply.
        self.gate(documents)

        content: list[dict[str, object]] = [{"type": "text", "text": instruction}]
        total_b64_mb = 0.0

        for doc in documents:
            _assert_exists(doc.path)
            b64 = self._read_pages_as_b64(doc)
            # Accurate payload accounting against the Vertex cap (base64 is what the API counts).
            raw = __import__("base64").b64decode(b64)
            total_b64_mb += base64_size_mb(raw)
            # LiteLLM/Vertex accept PDFs as a `file` content block with a data URI.
            content.append(
                {
                    "type": "file",
                    "file": {
                        "file_data": f"data:{doc.mime_type};base64,{b64}",
                    },
                }
            )

        cap_mb = self.capability.max_payload_mb
        notes: dict[str, object] = {"payload_cap_mb": cap_mb}
        if cap_mb is not None and total_b64_mb > cap_mb:
            notes["over_payload_cap"] = True
            notes["hint"] = "select fewer pages (page_ranges) to fit under the cap"

        return NormalizedContent(
            system=system,
            content=content,
            transport="pdf_native",
            image_count=0,
            sent_payload_mb=round(total_b64_mb, 4),
            notes=notes,
        )

"""Adapter contract + the capability gate.

An adapter turns a task's document input + text instruction into the message-content shape a
given provider expects, applying that provider's caveats:

* PDF + ``pdf_native`` -> pass the PDF through as a file part (Gemini).
* PDF + ``not pdf_native`` -> rasterize pages to images, enforce per-image size/resolution caps
  and format, attach as image parts (Grok et al. — Phase 2).
* gate out models that cannot do the task at all (text-only model on an image/PDF task).

The capability *gate* lives here (shared by every adapter) so the runner can mark a cell
``skipped`` with a reason instead of producing an unfair/garbage comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.providers.capabilities import ModelCapability


class CapabilityGateError(Exception):
    """Raised when a model cannot handle the requested input (record as skipped, not failed)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DocumentInput:
    """A document the task wants to send to the model."""

    path: str
    page_ranges: str | None = None  # 1-based, e.g. "1,3-5"; None = all pages
    mime_type: str = "application/pdf"


@dataclass(frozen=True)
class NormalizedContent:
    """Provider-ready message content + provenance about what the adapter did."""

    system: str
    content: list[dict[str, Any]]  # the user message's content blocks
    transport: str  # "pdf_native" | "rasterized_images" | "text_only"
    image_count: int = 0
    sent_payload_mb: float = 0.0
    notes: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter:
    """Base adapter: shared capability gating; subclasses implement ``normalize``."""

    def __init__(self, capability: ModelCapability) -> None:
        self.capability = capability

    # ------------------------------------------------------------------ gate
    def gate(self, documents: list[DocumentInput]) -> None:
        """Raise ``CapabilityGateError`` if this model cannot handle the given documents."""
        if not documents:
            return
        cap = self.capability
        if not cap.can_handle_documents():
            raise CapabilityGateError(
                f"{cap.model_id} is text-only ({sorted(m.value for m in cap.modalities)}); "
                "cannot process document/image input."
            )
        for doc in documents:
            is_pdf = doc.mime_type == "application/pdf" or str(doc.path).lower().endswith(".pdf")
            if is_pdf and not cap.pdf_native and not cap.vision:
                raise CapabilityGateError(
                    f"{cap.model_id} can neither ingest PDF natively nor accept rasterized images."
                )

    def normalize(
        self, *, system: str, instruction: str, documents: list[DocumentInput]
    ) -> NormalizedContent:  # pragma: no cover - overridden
        raise NotImplementedError

    @staticmethod
    def _read_pages_as_b64(doc: DocumentInput) -> str:
        from app.utils.pdf import extract_pages_as_base64

        return extract_pages_as_base64(doc.path, doc.page_ranges)


def get_adapter(capability: ModelCapability) -> ProviderAdapter:
    """Return the adapter for a model's provider.

    Phase 1 implements only the Gemini-Vertex (PDF-native) path. Non-native providers
    (rasterization) arrive in Phase 2 via the openai-compat / xai adapters.
    """
    from app.providers.adapters.gemini_vertex import GeminiVertexAdapter
    from app.providers.capabilities import Provider

    if capability.provider == Provider.vertex_ai:
        return GeminiVertexAdapter(capability)
    # Phase 2: vertex_partner / xai / openai_compatible rasterizing adapters.
    raise NotImplementedError(
        f"No adapter implemented yet for provider '{capability.provider.value}' "
        f"(model {capability.model_id}). Phase 1 ships the Gemini-Vertex adapter only."
    )


def _assert_exists(path: str) -> None:
    if not Path(path).is_file():
        raise FileNotFoundError(f"Document not found: {path}")

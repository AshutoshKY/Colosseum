"""Per-provider input normalization adapters."""

from __future__ import annotations

from app.providers.adapters.base import (
    CapabilityGateError,
    DocumentInput,
    NormalizedContent,
    ProviderAdapter,
    get_adapter,
)
from app.providers.adapters.gemini_vertex import GeminiVertexAdapter

__all__ = [
    "ProviderAdapter",
    "DocumentInput",
    "NormalizedContent",
    "CapabilityGateError",
    "GeminiVertexAdapter",
    "get_adapter",
]

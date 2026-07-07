"""Per-provider input normalization adapters."""

from __future__ import annotations

from app.providers.adapters.base import (
    CapabilityGateError,
    DocumentInput,
    NormalizedContent,
    ProviderAdapter,
    TextOnlyAdapter,
    get_adapter,
)
from app.providers.adapters.gemini_vertex import GeminiVertexAdapter
from app.providers.adapters.rasterizing import RasterizingAdapter

__all__ = [
    "ProviderAdapter",
    "DocumentInput",
    "NormalizedContent",
    "CapabilityGateError",
    "GeminiVertexAdapter",
    "RasterizingAdapter",
    "TextOnlyAdapter",
    "get_adapter",
]

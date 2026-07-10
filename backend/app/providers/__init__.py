"""Model-agnostic provider core: capabilities, registry, adapters, gateway, usage, pricing."""

from __future__ import annotations

from app.providers.adapters import DocumentInput
from app.providers.capabilities import (
    Access,
    Modality,
    ModelCapability,
    Provider,
    StructuredMethod,
)
from app.providers.gateway import GatewayResult, ModelGateway, ProviderAuthError
from app.providers.registry import get_capability, is_registered, list_models, registry
from app.providers.usage import NormalizedUsage, normalize_usage

__all__ = [
    "ModelCapability",
    "Modality",
    "Access",
    "Provider",
    "StructuredMethod",
    "registry",
    "get_capability",
    "list_models",
    "is_registered",
    "ModelGateway",
    "GatewayResult",
    "ProviderAuthError",
    "DocumentInput",
    "NormalizedUsage",
    "normalize_usage",
]

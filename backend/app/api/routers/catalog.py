"""Model catalog metadata and opt-in live verification."""

from __future__ import annotations

import importlib.util
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    AddModelIn,
    CatalogModelOut,
    CatalogOut,
    DiscoveredModelOut,
    DiscoverBedrockOut,
    DiscoverVertexOut,
    RegionInfo,
    RegionsOut,
    SetBedrockRegionIn,
    VerifyOut,
)
from app.core.config import get_settings
from app.providers.catalog import delete_custom_model_from_disk, save_custom_model_to_disk
from app.providers.capabilities import (
    Access,
    Modality,
    ModelCapability,
    Provider,
    StructuredMethod,
)
from app.providers.pricing.estimator import (
    load_rate_card,
    register_dynamic_model,
    resolve_pricing_ref,
)
from app.providers.registry import (
    catalog_meta,
    catalog_summary,
    gate_reason,
    is_registered,
    list_models,
    register_model,
    registry,
    unregister_model,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])
REPO_ROOT = Path(__file__).resolve().parents[4]

_REGION_NICKNAMES: dict[str, list[str]] = {
    "us-east-1": ["virginia", "n. virginia", "us-east"],
    "us-east-2": ["ohio", "us-east"],
    "us-west-2": ["oregon", "us-west"],
    "us-west-1": ["california", "us-west"],
    "ap-south-1": ["mumbai", "india", "asia pacific"],
    "eu-west-1": ["ireland", "europe"],
    "eu-central-1": ["frankfurt", "germany", "europe"],
    "ap-southeast-1": ["singapore", "asia pacific"],
    "ap-northeast-1": ["tokyo", "japan", "asia pacific"],
    "us-central1": ["iowa", "central"],
    "us-east4": ["virginia", "east"],
    "europe-west4": ["netherlands", "europe"],
    "asia-east1": ["taiwan", "asia"],
}


def _pricing(pricing_ref: str | None, card: dict[str, Any]) -> dict[str, float | None]:
    key = resolve_pricing_ref(pricing_ref, card)
    rates = (card.get("models") or {}).get(key, {}) if key else {}
    return {
        "input": rates.get("input_usd_per_million"),
        "output": rates.get("output_usd_per_million"),
        "input_per_million": rates.get("input_usd_per_million"),
        "output_per_million": rates.get("output_usd_per_million"),
        "cache_read_per_million": rates.get("cache_read_usd_per_million"),
        "thinking_per_million": rates.get("thinking_usd_per_million"),
    }


def _get_model_region(capability: ModelCapability, meta: dict) -> tuple[str, list[str]]:
    settings = get_settings()
    provider = capability.provider
    if provider == Provider.bedrock:
        default_region = capability.default_region or meta.get("region") or settings.aws_region_name or "us-east-1"
        regions = list(capability.regions) if capability.regions else [
            "us-east-1", "us-west-2", "ap-south-1", "eu-west-1", "us-east-2", "eu-central-1", "ap-southeast-1", "ap-northeast-1"
        ]
        return default_region, sorted(set(regions))
    if provider in (Provider.vertex_ai, Provider.vertex_partner):
        default_region = capability.vertex_location or settings.vertexai_location or "us-central1"
        regions = ["us-central1", "us-east4", "us-west1", "europe-west4", "asia-east1"]
        return default_region, sorted(set(regions))
    return "global", ["global"]


def _catalog_row(model_id: str, card: dict[str, Any]) -> CatalogModelOut:
    capability = registry[model_id]
    meta = catalog_meta.get(model_id, {})
    data = capability.model_dump(mode="json")
    rel_date = capability.release_date or meta.get("release_date")
    if not rel_date and model_id.startswith("openrouter/"):
        from app.providers.openrouter import lookup
        live = lookup(model_id)
        if live:
            rel_date = live.release_date

    region, regions = _get_model_region(capability, meta)

    return CatalogModelOut(
        id=model_id,
        model_id=model_id,
        name=capability.display_name,
        provider=capability.provider.value,
        family=str(meta.get("family") or "unknown"),
        enabled=capability.enabled,
        verified=capability.verified,
        gate_reason=gate_reason(model_id),
        release_date=rel_date,
        region=region,
        regions=regions,
        capabilities={
            "modalities": data["modalities"],
            "pdf_native": capability.pdf_native,
            "vision": capability.vision,
            "structured_method": capability.structured_method.value,
            "thinking": capability.thinking,
            "caching": capability.caching,
            "batch": capability.batch,
            "context_window": capability.context_window,
        },
        pricing=_pricing(capability.pricing_ref, card),
    )


@router.get("", response_model=CatalogOut)
def get_catalog() -> CatalogOut:
    card = load_rate_card()
    rows = [_catalog_row(cap.model_id, card) for cap in list_models()]
    rows.sort(key=lambda row: (row.provider, row.family, row.name))
    providers: dict[str, list[CatalogModelOut]] = defaultdict(list)
    for row in rows:
        providers[row.provider].append(row)
    return CatalogOut(models=rows, providers=dict(providers), summary=catalog_summary())


# Candidate Vertex AI & Vertex Partner models for discovery & status checking
_VERTEX_CANDIDATES = [
    # Google Gemini
    {"id": "gemini-3.1-pro", "pub": "google", "name": "Gemini 3.1 Pro (Preview)", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": True, "in_m": 1.25, "out_m": 10.0, "rel": "2026-02-15"},
    {"id": "gemini-3-flash", "pub": "google", "name": "Gemini 3 Flash (Preview)", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": True, "in_m": 0.3, "out_m": 2.5, "rel": "2025-12-15"},
    {"id": "vertex_ai/gemini-2.0-flash", "pub": "google", "name": "Gemini 2.0 Flash", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": True, "in_m": 0.1, "out_m": 0.4, "rel": "2024-12-11"},
    {"id": "vertex_ai/gemini-2.0-flash-lite", "pub": "google", "name": "Gemini 2.0 Flash-Lite", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": True, "in_m": 0.075, "out_m": 0.3, "rel": "2025-02-05"},
    {"id": "vertex_ai/gemini-2.0-pro-exp", "pub": "google", "name": "Gemini 2.0 Pro Experimental", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": True, "in_m": 1.25, "out_m": 10.0, "rel": "2025-02-05"},
    {"id": "vertex_ai/gemini-1.5-pro", "pub": "google", "name": "Gemini 1.5 Pro", "family": "gemini", "pdf": True, "vision": True, "ctx": 2000000, "thinking": False, "in_m": 1.25, "out_m": 5.0, "rel": "2024-02-15"},
    {"id": "vertex_ai/gemini-1.5-flash", "pub": "google", "name": "Gemini 1.5 Flash", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": False, "in_m": 0.075, "out_m": 0.3, "rel": "2024-05-14"},
    {"id": "vertex_ai/gemini-1.5-flash-8b", "pub": "google", "name": "Gemini 1.5 Flash-8B", "family": "gemini", "pdf": True, "vision": True, "ctx": 1000000, "thinking": False, "in_m": 0.0375, "out_m": 0.15, "rel": "2024-10-03"},

    # Anthropic Claude on Model Garden
    {"id": "vertex_ai/claude-3-7-sonnet@20250219", "pub": "anthropic", "name": "Claude 3.7 Sonnet (Vertex)", "family": "claude", "pdf": True, "vision": True, "ctx": 200000, "thinking": True, "in_m": 3.0, "out_m": 15.0, "rel": "2025-02-19"},
    {"id": "vertex_ai/claude-3-5-sonnet-v2@20241022", "pub": "anthropic", "name": "Claude 3.5 Sonnet v2 (Vertex)", "family": "claude", "pdf": True, "vision": True, "ctx": 200000, "thinking": False, "in_m": 3.0, "out_m": 15.0, "rel": "2024-10-22"},
    {"id": "vertex_ai/claude-3-5-haiku@20241022", "pub": "anthropic", "name": "Claude 3.5 Haiku (Vertex)", "family": "claude", "pdf": True, "vision": True, "ctx": 200000, "thinking": False, "in_m": 0.8, "out_m": 4.0, "rel": "2024-10-22"},
    {"id": "vertex_ai/claude-3-opus@20240229", "pub": "anthropic", "name": "Claude 3 Opus (Vertex)", "family": "claude", "pdf": True, "vision": True, "ctx": 200000, "thinking": False, "in_m": 15.0, "out_m": 75.0, "rel": "2024-02-29"},
    {"id": "vertex_ai/claude-3-haiku@20240307", "pub": "anthropic", "name": "Claude 3 Haiku (Vertex)", "family": "claude", "pdf": True, "vision": True, "ctx": 200000, "thinking": False, "in_m": 0.25, "out_m": 1.25, "rel": "2024-03-07"},

    # Meta Llama on Model Garden
    {"id": "vertex_ai/meta/llama-3.3-70b-instruct-maas", "pub": "meta", "name": "Llama 3.3 70B Instruct (Vertex)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.7, "out_m": 0.8, "rel": "2024-12-06"},
    {"id": "vertex_ai/meta/llama-3.2-90b-vision-instruct-maas", "pub": "meta", "name": "Llama 3.2 90B Vision (Vertex)", "family": "llama", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.6, "out_m": 0.6, "rel": "2024-09-25"},
    {"id": "vertex_ai/meta/llama-3.2-11b-vision-instruct-maas", "pub": "meta", "name": "Llama 3.2 11B Vision (Vertex)", "family": "llama", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.16, "out_m": 0.16, "rel": "2024-09-25"},
    {"id": "vertex_ai/meta/llama-3.2-3b-instruct-maas", "pub": "meta", "name": "Llama 3.2 3B Instruct (Vertex)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.04, "out_m": 0.04, "rel": "2024-09-25"},
    {"id": "vertex_ai/meta/llama-3.2-1b-instruct-maas", "pub": "meta", "name": "Llama 3.2 1B Instruct (Vertex)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.02, "out_m": 0.02, "rel": "2024-09-25"},
    {"id": "vertex_ai/meta/llama-3.1-405b-instruct-maas", "pub": "meta", "name": "Llama 3.1 405B Instruct (Vertex)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.5, "out_m": 0.7, "rel": "2024-07-23"},
    {"id": "vertex_ai/meta/llama-3.1-70b-instruct-maas", "pub": "meta", "name": "Llama 3.1 70B Instruct (Vertex)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.5, "out_m": 0.7, "rel": "2024-07-23"},
    {"id": "vertex_ai/meta/llama-3.1-8b-instruct-maas", "pub": "meta", "name": "Llama 3.1 8B Instruct (Vertex)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.15, "out_m": 0.15, "rel": "2024-07-23"},

    # Mistral AI on Model Garden
    {"id": "vertex_ai/mistral-large-2411", "pub": "mistralai", "name": "Mistral Large (2411, Vertex)", "family": "mistral", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 2.0, "out_m": 6.0, "rel": "2024-11-18"},
    {"id": "vertex_ai/mistral-large-2407", "pub": "mistralai", "name": "Mistral Large (2407, Vertex)", "family": "mistral", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 2.0, "out_m": 6.0, "rel": "2024-07-24"},
    {"id": "vertex_ai/pixtral-large-2411", "pub": "mistralai", "name": "Pixtral Large (Vertex)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 2.0, "out_m": 6.0, "rel": "2024-11-18"},
    {"id": "vertex_ai/pixtral-12b-2409", "pub": "mistralai", "name": "Pixtral 12B (Vertex)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.1, "out_m": 0.3, "rel": "2024-09-10"},
    {"id": "vertex_ai/codestral-2501", "pub": "mistralai", "name": "Codestral 2501 (Vertex)", "family": "mistral", "pdf": False, "vision": False, "ctx": 256000, "thinking": False, "in_m": 0.3, "out_m": 0.9, "rel": "2025-01-14"},
    {"id": "vertex_ai/mistral-small-2409", "pub": "mistralai", "name": "Mistral Small (2409, Vertex)", "family": "mistral", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.2, "out_m": 0.6, "rel": "2024-09-17"},
    {"id": "vertex_ai/mistral-nemo@2407", "pub": "mistralai", "name": "Mistral Nemo (Vertex)", "family": "mistral", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.15, "out_m": 0.15, "rel": "2024-07-18"},

    # Qwen on Model Garden
    {"id": "vertex_ai/qwen/qwen2.5-72b-instruct-maas", "pub": "qwen", "name": "Qwen 2.5 72B Instruct (Vertex)", "family": "qwen", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.2, "out_m": 0.6, "rel": "2024-09-19"},
    {"id": "vertex_ai/qwen/qwen2.5-coder-32b-instruct-maas", "pub": "qwen", "name": "Qwen 2.5 Coder 32B (Vertex)", "family": "qwen", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.25, "out_m": 0.8, "rel": "2024-11-12"},
    {"id": "vertex_ai/qwen/qwen2.5-7b-instruct-maas", "pub": "qwen", "name": "Qwen 2.5 7B Instruct (Vertex)", "family": "qwen", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.1, "out_m": 0.2, "rel": "2024-09-19"},
    {"id": "vertex_ai/qwen/qwq-32b-preview-maas", "pub": "qwen", "name": "QwQ 32B Preview (Vertex)", "family": "qwen", "pdf": False, "vision": False, "ctx": 32768, "thinking": True, "in_m": 0.25, "out_m": 0.8, "rel": "2024-11-28"},

    # DeepSeek on Model Garden
    {"id": "vertex_ai/deepseek-ai/deepseek-r1-maas", "pub": "deepseek-ai", "name": "DeepSeek R1 (Vertex)", "family": "deepseek", "pdf": False, "vision": False, "ctx": 163840, "thinking": True, "in_m": 1.35, "out_m": 5.4, "rel": "2025-01-20"},
    {"id": "vertex_ai/deepseek-ai/deepseek-v3-maas", "pub": "deepseek-ai", "name": "DeepSeek V3 (Vertex)", "family": "deepseek", "pdf": False, "vision": False, "ctx": 163840, "thinking": False, "in_m": 0.27, "out_m": 1.1, "rel": "2024-12-26"},

    # Google Gemma 2 on Model Garden
    {"id": "vertex_ai/google/gemma-2-27b-it", "pub": "google", "name": "Gemma 2 27B IT (Vertex)", "family": "open_models", "pdf": False, "vision": False, "ctx": 8192, "thinking": False, "in_m": 0.1, "out_m": 0.3, "rel": "2024-06-27"},
    {"id": "vertex_ai/google/gemma-2-9b-it", "pub": "google", "name": "Gemma 2 9B IT (Vertex)", "family": "open_models", "pdf": False, "vision": False, "ctx": 8192, "thinking": False, "in_m": 0.05, "out_m": 0.1, "rel": "2024-06-27"},
    {"id": "vertex_ai/google/gemma-2-2b-it", "pub": "google", "name": "Gemma 2 2B IT (Vertex)", "family": "open_models", "pdf": False, "vision": False, "ctx": 8192, "thinking": False, "in_m": 0.02, "out_m": 0.04, "rel": "2024-06-27"},
]


@router.post("/discover/vertex", response_model=DiscoverVertexOut)
def discover_vertex_models(location: str = "") -> DiscoverVertexOut:
    """Discover available Vertex AI & Partner Model Garden models and check live readiness."""
    settings = get_settings()
    has_creds = settings.has_vertex_credentials
    project = settings.vertexai_project or os.environ.get("GOOGLE_CLOUD_PROJECT") or "vertex-internal-testing"
    target_location = location.strip() or settings.vertexai_location or "us-central1"

    out_list: list[DiscoveredModelOut] = []
    for item in _VERTEX_CANDIDATES:
        mid = item["id"]
        in_cat = is_registered(mid)
        cap = registry.get(mid)
        is_cal = cap.verified if (cap and cap.enabled) else None

        modalities = ["text"]
        if item.get("pdf"):
            modalities.append("pdf")
        if item.get("vision"):
            modalities.append("image")

        status = "registered" if in_cat else "available"
        if cap and cap.verified:
            status = "callable"
        elif in_cat and not (cap and cap.enabled):
            status = "unverified"

        out_list.append(
            DiscoveredModelOut(
                model_id=mid,
                name=item["name"],
                provider="vertex_ai" if item["pub"] == "google" else "vertex_partner",
                family=item["family"],
                publisher=item["pub"],
                description=f"{item['pub'].capitalize()} {item['family'].capitalize()} model on Vertex Model Garden ({target_location})",
                is_registered=in_cat,
                is_callable=is_cal,
                region=target_location,
                regions=[target_location],
                capabilities={
                    "modalities": modalities,
                    "pdf_native": bool(item.get("pdf")),
                    "vision": bool(item.get("vision")),
                    "context_window": item.get("ctx"),
                    "thinking": bool(item.get("thinking")),
                    "caching": item.get("pub") == "google" or item.get("pub") == "anthropic",
                    "structured_method": "json_schema" if item.get("pub") == "google" else "tools" if item.get("pub") == "anthropic" else "json_mode",
                },
                pricing={
                    "input": item.get("in_m", 0.0),
                    "output": item.get("out_m", 0.0),
                    "input_per_million": item.get("in_m", 0.0),
                    "output_per_million": item.get("out_m", 0.0),
                    "cache_read_per_million": 0.05 if item.get("pub") in ("google", "anthropic") else None,
                    "thinking_per_million": item.get("out_m", 0.0) if item.get("thinking") else None,
                },
                release_date=item.get("rel"),
                status=status,
            )
        )

    return DiscoverVertexOut(
        total=len(out_list),
        has_credentials=has_creds,
        project=project,
        location=target_location,
        available_locations=["us-central1", "us-east4", "us-west1", "europe-west4", "asia-east1", "asia-southeast1"],
        discovered=out_list,
    )


# Candidate AWS Bedrock models for multi-region discovery & status checking
_BEDROCK_CANDIDATES = [
    # Qwen (Alibaba)
    {"id": "bedrock-qwen3-vl-235b", "transport": "qwen.qwen3-vl-235b-a22b", "pub": "alibaba", "name": "Qwen3-VL 235B A22B (Bedrock)", "family": "qwen", "pdf": False, "vision": True, "ctx": 131072, "thinking": False, "in_m": 0.55, "out_m": 2.2, "rel": "2025-07-20"},
    {"id": "bedrock-qwen3-235b-instruct", "transport": "qwen.qwen3-235b-a22b-2507-v1:0", "pub": "alibaba", "name": "Qwen3 235B Instruct (Bedrock)", "family": "qwen", "pdf": False, "vision": False, "ctx": 131072, "thinking": False, "in_m": 0.55, "out_m": 2.2, "rel": "2025-07-20"},
    {"id": "bedrock-qwen3-next-80b", "transport": "qwen.qwen3-next-80b-a3b", "pub": "alibaba", "name": "Qwen3 Next 80B A3B (Bedrock)", "family": "qwen", "pdf": False, "vision": False, "ctx": 131072, "thinking": False, "in_m": 0.35, "out_m": 1.4, "rel": "2025-07-20"},
    {"id": "bedrock-qwen3-coder-next", "transport": "qwen.qwen3-coder-next", "pub": "alibaba", "name": "Qwen3 Coder Next (Bedrock)", "family": "qwen", "pdf": False, "vision": False, "ctx": 131072, "thinking": False, "in_m": 0.45, "out_m": 1.8, "rel": "2025-09-15"},
    {"id": "bedrock-qwen3-coder-480b", "transport": "qwen.qwen3-coder-480b-a35b-v1:0", "pub": "alibaba", "name": "Qwen3 Coder 480B (Bedrock)", "family": "qwen", "pdf": False, "vision": False, "ctx": 131072, "thinking": False, "in_m": 0.8, "out_m": 3.2, "rel": "2025-07-20"},
    {"id": "bedrock-qwen3-coder-30b", "transport": "qwen.qwen3-coder-30b-a3b-v1:0", "pub": "alibaba", "name": "Qwen3 Coder 30B (Bedrock)", "family": "qwen", "pdf": False, "vision": False, "ctx": 131072, "thinking": False, "in_m": 0.15, "out_m": 0.6, "rel": "2025-07-20"},
    {"id": "bedrock-qwen3-32b", "transport": "qwen.qwen3-32b-v1:0", "pub": "alibaba", "name": "Qwen3 32B (Bedrock)", "family": "qwen", "pdf": False, "vision": False, "ctx": 131072, "thinking": False, "in_m": 0.15, "out_m": 0.6, "rel": "2025-07-20"},

    # Amazon Nova
    {"id": "bedrock-nova-2-lite", "transport": "global.amazon.nova-2-lite-v1:0", "pub": "amazon", "name": "Amazon Nova 2 Lite (Bedrock)", "family": "nova", "pdf": False, "vision": True, "ctx": 300000, "thinking": False, "in_m": 0.06, "out_m": 0.24, "rel": "2025-11-30"},
    {"id": "bedrock-nova-pro", "transport": "us.amazon.nova-pro-v1:0", "pub": "amazon", "name": "Amazon Nova Pro (Bedrock)", "family": "nova", "pdf": False, "vision": True, "ctx": 300000, "thinking": False, "in_m": 0.84, "out_m": 3.36, "rel": "2024-12-03"},
    {"id": "bedrock-nova-lite", "transport": "us.amazon.nova-lite-v1:0", "pub": "amazon", "name": "Amazon Nova Lite (Bedrock)", "family": "nova", "pdf": False, "vision": True, "ctx": 300000, "thinking": False, "in_m": 0.063, "out_m": 0.252, "rel": "2024-12-03"},
    {"id": "bedrock-nova-micro", "transport": "us.amazon.nova-micro-v1:0", "pub": "amazon", "name": "Amazon Nova Micro (Bedrock)", "family": "nova", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.037, "out_m": 0.148, "rel": "2024-12-03"},

    # Anthropic Claude on Bedrock
    {"id": "bedrock-claude-fable-5-1", "transport": "us.anthropic.claude-fable-5-1", "pub": "anthropic", "name": "Claude Fable 5.1 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 10.0, "out_m": 50.0, "rel": "2026-09-01"},
    {"id": "bedrock-claude-fable-5", "transport": "us.anthropic.claude-fable-5", "pub": "anthropic", "name": "Claude Fable 5 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 10.0, "out_m": 50.0, "rel": "2026-08-01"},
    {"id": "bedrock-claude-opus-5", "transport": "us.anthropic.claude-opus-5", "pub": "anthropic", "name": "Claude Opus 5 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 5.0, "out_m": 25.0, "rel": "2026-07-24"},
    {"id": "bedrock-claude-sonnet-5", "transport": "us.anthropic.claude-sonnet-5", "pub": "anthropic", "name": "Claude Sonnet 5 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 2.0, "out_m": 10.0, "rel": "2026-06-30"},
    {"id": "bedrock-claude-opus-4-6", "transport": "us.anthropic.claude-opus-4-6-v1", "pub": "anthropic", "name": "Claude Opus 4.6 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 15.0, "out_m": 75.0, "rel": "2026-02-15"},
    {"id": "bedrock-claude-opus-4-5", "transport": "global.anthropic.claude-opus-4-5-20251101-v1:0", "pub": "anthropic", "name": "Claude Opus 4.5 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 15.0, "out_m": 75.0, "rel": "2025-11-01"},
    {"id": "bedrock-claude-sonnet-4-6", "transport": "us.anthropic.claude-sonnet-4-6", "pub": "anthropic", "name": "Claude Sonnet 4.6 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 3.0, "out_m": 15.0, "rel": "2026-02-15"},
    {"id": "bedrock-claude-sonnet-4", "transport": "us.anthropic.claude-sonnet-4-20250514-v1:0", "pub": "anthropic", "name": "Claude Sonnet 4 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 3.0, "out_m": 15.0, "rel": "2025-05-14"},
    {"id": "bedrock-claude-3-7-sonnet", "transport": "us.anthropic.claude-3-7-sonnet-20250219-v1:0", "pub": "anthropic", "name": "Claude 3.7 Sonnet (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": True, "in_m": 3.0, "out_m": 15.0, "rel": "2025-02-19"},
    {"id": "bedrock-claude-3-5-sonnet-v2", "transport": "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "pub": "anthropic", "name": "Claude 3.5 Sonnet v2 (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": False, "in_m": 3.0, "out_m": 15.0, "rel": "2024-10-22"},
    {"id": "bedrock-claude-3-5-haiku", "transport": "us.anthropic.claude-3-5-haiku-20241022-v1:0", "pub": "anthropic", "name": "Claude 3.5 Haiku (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": False, "in_m": 0.8, "out_m": 4.0, "rel": "2024-10-22"},
    {"id": "bedrock-claude-3-haiku", "transport": "anthropic.claude-3-haiku-20240307-v1:0", "pub": "anthropic", "name": "Claude 3 Haiku (Bedrock)", "family": "claude", "pdf": False, "vision": True, "ctx": 200000, "thinking": False, "in_m": 0.25, "out_m": 1.25, "rel": "2024-03-07"},

    # Google Gemma on Bedrock
    {"id": "bedrock-gemma-3-27b", "transport": "google.gemma-3-27b-it", "pub": "google", "name": "Gemma 3 27B IT (Bedrock)", "family": "gemma", "pdf": False, "vision": True, "ctx": 131072, "thinking": False, "in_m": 0.15, "out_m": 0.45, "rel": "2025-02-15"},
    {"id": "bedrock-gemma-3-12b", "transport": "google.gemma-3-12b-it", "pub": "google", "name": "Gemma 3 12B IT (Bedrock)", "family": "gemma", "pdf": False, "vision": True, "ctx": 131072, "thinking": False, "in_m": 0.08, "out_m": 0.24, "rel": "2025-02-15"},

    # OpenAI GPT-OSS on Bedrock
    {"id": "bedrock-gpt-oss-120b", "transport": "openai.gpt-oss-120b-1:0", "pub": "openai", "name": "GPT-OSS 120B (Bedrock)", "family": "gpt_oss", "pdf": False, "vision": False, "ctx": 131072, "thinking": True, "in_m": 0.4, "out_m": 1.6, "rel": "2025-07-10"},
    {"id": "bedrock-gpt-oss-20b", "transport": "openai.gpt-oss-20b-1:0", "pub": "openai", "name": "GPT-OSS 20B (Bedrock)", "family": "gpt_oss", "pdf": False, "vision": False, "ctx": 131072, "thinking": True, "in_m": 0.1, "out_m": 0.4, "rel": "2025-07-10"},

    # OpenAI GPT-5.6 (Luna / Terra / Sol) on Bedrock
    {"id": "bedrock-gpt-5-6-luna", "transport": "us.openai.gpt-5.6-luna", "pub": "openai", "name": "GPT-5.6 Luna (Bedrock)", "family": "gpt_5_6", "pdf": False, "vision": True, "ctx": 1050000, "thinking": False, "in_m": 0.5, "out_m": 2.0, "rel": "2026-07-15"},
    {"id": "bedrock-gpt-5-6-terra", "transport": "us.openai.gpt-5.6-terra", "pub": "openai", "name": "GPT-5.6 Terra (Bedrock)", "family": "gpt_5_6", "pdf": False, "vision": True, "ctx": 1050000, "thinking": True, "in_m": 2.0, "out_m": 8.0, "rel": "2026-07-15"},
    {"id": "bedrock-gpt-5-6-sol", "transport": "us.openai.gpt-5.6-sol", "pub": "openai", "name": "GPT-5.6 Sol (Bedrock)", "family": "gpt_5_6", "pdf": False, "vision": True, "ctx": 1050000, "thinking": True, "in_m": 5.0, "out_m": 20.0, "rel": "2026-07-15"},

    # OpenAI GPT-6 Astra on Bedrock
    {"id": "bedrock-gpt-6-astra", "transport": "us.openai.gpt-6-astra", "pub": "openai", "name": "GPT-6 Astra (Bedrock)", "family": "gpt_6", "pdf": False, "vision": True, "ctx": 1050000, "thinking": True, "in_m": 8.0, "out_m": 32.0, "rel": "2026-09-01"},

    # Mistral on Bedrock
    {"id": "bedrock-mistral-large-3", "transport": "mistral.mistral-large-3-675b-instruct", "pub": "mistral", "name": "Mistral Large 3 675B (Bedrock)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 2.0, "out_m": 6.0, "rel": "2025-06-10"},
    {"id": "bedrock-devstral-2", "transport": "mistral.devstral-2-123b", "pub": "mistral", "name": "Devstral 2 123B (Bedrock)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.4, "out_m": 1.2, "rel": "2025-10-15"},
    {"id": "bedrock-magistral-small", "transport": "mistral.magistral-small-2509", "pub": "mistral", "name": "Magistral Small 2509 (Bedrock)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": True, "in_m": 0.15, "out_m": 0.45, "rel": "2025-09-15"},
    {"id": "bedrock-ministral-3-8b", "transport": "mistral.ministral-3-8b-instruct", "pub": "mistral", "name": "Ministral 3 8B (Bedrock)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.1, "out_m": 0.3, "rel": "2024-10-15"},
    {"id": "bedrock-ministral-3-14b", "transport": "mistral.ministral-3-14b-instruct", "pub": "mistral", "name": "Ministral 3 14B (Bedrock)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.15, "out_m": 0.45, "rel": "2024-10-15"},
    {"id": "bedrock-pixtral-large", "transport": "mistral.pixtral-large-2502-v1:0", "pub": "mistral", "name": "Pixtral Large 2502 (Bedrock)", "family": "mistral", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 2.0, "out_m": 6.0, "rel": "2025-02-15"},

    # DeepSeek on Bedrock
    {"id": "bedrock-deepseek-v3-2", "transport": "deepseek.v3.2", "pub": "deepseek", "name": "DeepSeek V3.2 (Bedrock)", "family": "deepseek", "pdf": False, "vision": False, "ctx": 128000, "thinking": True, "in_m": 0.27, "out_m": 1.1, "rel": "2025-09-10"},
    {"id": "bedrock-deepseek-r1", "transport": "deepseek.r1-v1:0", "pub": "deepseek", "name": "DeepSeek R1 (Bedrock)", "family": "deepseek", "pdf": False, "vision": False, "ctx": 128000, "thinking": True, "in_m": 0.55, "out_m": 2.2, "rel": "2025-01-20"},

    # Meta Llama on Bedrock
    {"id": "bedrock-llama-3-3-70b", "transport": "meta.llama3-3-70b-instruct-v1:0", "pub": "meta", "name": "Llama 3.3 70B Instruct (Bedrock)", "family": "llama", "pdf": False, "vision": False, "ctx": 128000, "thinking": False, "in_m": 0.72, "out_m": 0.72, "rel": "2024-12-06"},
    {"id": "bedrock-llama3-70b", "transport": "meta.llama3-70b-instruct-v1:0", "pub": "meta", "name": "Llama 3 70B Instruct (Bedrock)", "family": "llama", "pdf": False, "vision": False, "ctx": 8192, "thinking": False, "in_m": 0.5, "out_m": 0.7, "rel": "2024-04-18"},
    {"id": "bedrock-llama4-scout-17b", "transport": "meta.llama4-scout-17b-instruct-v1:0", "pub": "meta", "name": "Llama 4 Scout 17B (Bedrock)", "family": "llama", "pdf": False, "vision": True, "ctx": 131072, "thinking": False, "in_m": 0.25, "out_m": 0.75, "rel": "2025-04-15"},
    {"id": "bedrock-llama4-maverick-17b", "transport": "meta.llama4-maverick-17b-instruct-v1:0", "pub": "meta", "name": "Llama 4 Maverick 17B (Bedrock)", "family": "llama", "pdf": False, "vision": True, "ctx": 131072, "thinking": False, "in_m": 0.45, "out_m": 1.35, "rel": "2025-04-15"},

    # GLM / MiniMax / Kimi / Nemotron
    {"id": "bedrock-glm-5", "transport": "zai.glm-5", "pub": "z-ai", "name": "GLM-5 (Bedrock)", "family": "glm", "pdf": False, "vision": False, "ctx": 128000, "thinking": True, "in_m": 1.0, "out_m": 3.2, "rel": "2026-01-15"},
    {"id": "bedrock-glm-4-7", "transport": "zai.glm-4.7", "pub": "z-ai", "name": "GLM-4.7 (Bedrock)", "family": "glm", "pdf": False, "vision": False, "ctx": 128000, "thinking": True, "in_m": 0.6, "out_m": 2.2, "rel": "2025-10-20"},
    {"id": "bedrock-glm-4-7-flash", "transport": "zai.glm-4.7-flash", "pub": "z-ai", "name": "GLM-4.7 Flash (Bedrock)", "family": "glm", "pdf": False, "vision": False, "ctx": 128000, "thinking": True, "in_m": 0.1, "out_m": 0.4, "rel": "2026-02-06"},
    {"id": "bedrock-minimax-m2-5", "transport": "minimax.minimax-m2.5", "pub": "minimax", "name": "MiniMax M2.5 (Bedrock)", "family": "minimax", "pdf": False, "vision": False, "ctx": 128000, "thinking": True, "in_m": 0.4, "out_m": 1.6, "rel": "2025-10-20"},
    {"id": "bedrock-kimi-k2-5", "transport": "moonshotai.kimi-k2.5", "pub": "moonshotai", "name": "Kimi K2.5 (Bedrock)", "family": "kimi", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.6, "out_m": 2.5, "rel": "2025-11-15"},
    {"id": "bedrock-nemotron-nano-12b-vl", "transport": "nvidia.nemotron-nano-12b-v2", "pub": "nvidia", "name": "Nemotron Nano 12B v2 (Bedrock)", "family": "nemotron", "pdf": False, "vision": True, "ctx": 128000, "thinking": False, "in_m": 0.1, "out_m": 0.4, "rel": "2025-05-15"},
]

_BEDROCK_PUB_MAP = {
    "zai": "z-ai",
    "z.ai": "z-ai",
    "anthropic": "anthropic",
    "amazon": "amazon",
    "meta": "meta",
    "mistral": "mistral",
    "mistralai": "mistral",
    "deepseek": "deepseek",
    "google": "google",
    "openai": "openai",
    "qwen": "alibaba",
    "alibaba": "alibaba",
    "cohere": "cohere",
    "stability": "stability",
    "stability ai": "stability",
    "writer": "writer",
    "twelvelabs": "twelvelabs",
    "ai21": "ai21",
    "ai21 labs": "ai21",
    "moonshotai": "moonshotai",
    "moonshot": "moonshotai",
    "minimax": "minimax",
    "nvidia": "nvidia",
    "xai": "xai",
}


def _infer_bedrock_pub_and_family(raw_id: str, provider_name: str | None = None) -> tuple[str, str]:
    clean_id = raw_id.lower()
    for prefix in ("us.", "global.", "eu.", "ap.", "cr."):
        if clean_id.startswith(prefix):
            clean_id = clean_id[len(prefix):]
    parts = clean_id.split(".")
    pub_raw = parts[0] if len(parts) > 1 else (provider_name or "aws").lower()
    clean_pub = pub_raw.replace(" ", "").replace("_", "")
    pub = _BEDROCK_PUB_MAP.get(clean_pub, _BEDROCK_PUB_MAP.get((provider_name or "").lower().replace(" ", ""), pub_raw))

    fam = "bedrock"
    if "glm" in clean_id:
        fam = "glm"
    elif "claude" in clean_id:
        fam = "claude"
    elif "nova" in clean_id:
        fam = "nova"
    elif "llama" in clean_id:
        fam = "llama"
    elif any(k in clean_id for k in ("mistral", "pixtral", "devstral", "magistral", "ministral", "codestral")):
        fam = "mistral"
    elif "deepseek" in clean_id:
        fam = "deepseek"
    elif "gemma" in clean_id:
        fam = "gemma"
    elif "qwen" in clean_id:
        fam = "qwen"
    elif "gpt-6" in clean_id:
        fam = "gpt_6"
    elif "gpt-5.6" in clean_id or "gpt-5-6" in clean_id:
        fam = "gpt_5_6"
    elif "gpt" in clean_id:
        fam = "gpt_oss"
    elif "command" in clean_id or ("embed" in clean_id and "cohere" in clean_id):
        fam = "cohere"
    elif "kimi" in clean_id:
        fam = "kimi"
    elif "minimax" in clean_id:
        fam = "minimax"
    elif "nemotron" in clean_id:
        fam = "nemotron"
    elif "grok" in clean_id:
        fam = "grok"
    else:
        fam = pub

    return pub, fam


def _estimate_bedrock_pricing(pub: str, fam: str, model_id: str, card: dict[str, Any]) -> dict[str, float | None]:
    for key in (model_id, f"bedrock_{fam}", fam, f"bedrock_{pub}", pub):
        ref_key = resolve_pricing_ref(key, card)
        rates = (card.get("models") or {}).get(ref_key, {}) if ref_key else {}
        if rates:
            return {
                "input": rates.get("input_usd_per_million", 0.0),
                "output": rates.get("output_usd_per_million", 0.0),
                "input_per_million": rates.get("input_usd_per_million", 0.0),
                "output_per_million": rates.get("output_usd_per_million", 0.0),
                "cache_read_per_million": rates.get("cache_read_usd_per_million"),
                "thinking_per_million": rates.get("thinking_usd_per_million"),
            }
    return {
        "input": 0.5,
        "output": 1.5,
        "input_per_million": 0.5,
        "output_per_million": 1.5,
        "cache_read_per_million": None,
        "thinking_per_million": None,
    }


@router.post("/discover/bedrock", response_model=DiscoverBedrockOut)
def discover_bedrock_models(region: str = "", q: str = "") -> DiscoverBedrockOut:
    """Discover all available AWS Bedrock models (foundation models & inference profiles) and report live readiness."""
    settings = get_settings()
    token = settings.aws_bearer_token_bedrock or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    has_creds = bool(token or (settings.aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")))
    target_region = region.strip() or settings.aws_region_name or "us-east-1"
    card = load_rate_card()

    reg_bedrock_models = list_models(provider=Provider.bedrock)
    reg_by_trans: dict[str, ModelCapability] = {
        cap.transport_model.replace("bedrock/", ""): cap for cap in reg_bedrock_models
    }
    reg_by_id: dict[str, ModelCapability] = {
        cap.model_id: cap for cap in reg_bedrock_models
    }

    discovered_dict: dict[str, DiscoveredModelOut] = {}

    # 1. Query live AWS Bedrock Foundation Models and Inference Profiles
    if has_creds:
        try:
            import boto3

            client_kwargs = {"region_name": target_region}
            acc_key = settings.aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
            sec_key = settings.aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
            if acc_key and sec_key:
                client_kwargs["aws_access_key_id"] = acc_key
                client_kwargs["aws_secret_access_key"] = sec_key
            client = boto3.client("bedrock", **client_kwargs)

            # A. Foundation Models
            try:
                fm_res = client.list_foundation_models()
                for item in fm_res.get("modelSummaries", []):
                    raw_id = item.get("modelId", "")
                    if not raw_id:
                        continue

                    pub, fam = _infer_bedrock_pub_and_family(raw_id, item.get("providerName"))
                    input_mods = item.get("inputModalities", [])
                    output_mods = item.get("outputModalities", [])

                    modalities = ["text"]
                    if "IMAGE" in input_mods:
                        modalities.append("image")
                    if "EMBEDDING" in output_mods:
                        modalities.append("embedding")

                    has_vision = "IMAGE" in input_mods
                    is_thinking = any(
                        k in raw_id.lower()
                        for k in ("thinking", "r1", "glm-5", "glm-4.7", "opus-4", "opus-5", "sonnet-4", "sonnet-5", "sonnet-3-7", "fable", "magistral", "gpt-oss", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-6")
                    )
                    ctx = 1050000 if any(k in raw_id.lower() for k in ("gpt-5.6", "gpt-6")) else 200000 if "claude" in raw_id.lower() or "glm" in raw_id.lower() else 300000 if "nova" in raw_id.lower() else 128000

                    # Match with existing registered catalog models
                    matched_cap = reg_by_trans.get(raw_id) or reg_by_id.get(f"bedrock-{raw_id.replace(':', '-').replace('.', '-')}")
                    in_cat = matched_cap is not None
                    is_cal = (matched_cap.verified if (matched_cap and matched_cap.enabled) else None) if in_cat else True
                    status = "callable" if (matched_cap and matched_cap.verified) else "registered" if in_cat else "available"

                    m_id = matched_cap.model_id if matched_cap else f"bedrock-{raw_id.replace(':', '-').replace('.', '-')}"
                    name = matched_cap.display_name if matched_cap else f"{item.get('modelName') or raw_id} (Bedrock)"

                    # Release date handling
                    rel_date = None
                    lifecycle = item.get("modelLifecycle")
                    if isinstance(lifecycle, dict) and lifecycle.get("startOfLifeTime"):
                        rel_date = str(lifecycle["startOfLifeTime"]).split()[0].split("T")[0]

                    pricing = _estimate_bedrock_pricing(pub, fam, raw_id, card)

                    discovered_dict[raw_id] = DiscoveredModelOut(
                        model_id=m_id,
                        name=name,
                        provider="bedrock",
                        family=fam,
                        publisher=pub,
                        description=f"{pub.capitalize()} {fam.capitalize()} foundation model on AWS Bedrock ({target_region})",
                        is_registered=in_cat,
                        is_callable=is_cal,
                        region=target_region,
                        regions=[target_region],
                        capabilities={
                            "modalities": modalities,
                            "pdf_native": False,
                            "vision": has_vision,
                            "context_window": ctx,
                            "thinking": is_thinking,
                            "caching": pub == "anthropic",
                            "structured_method": "tools" if pub == "anthropic" else "json_mode",
                        },
                        pricing=pricing,
                        release_date=rel_date,
                        status=status,
                    )
            except Exception:
                pass

            # B. Cross-Region / System Inference Profiles
            try:
                prof_res = client.list_inference_profiles()
                for prof in prof_res.get("inferenceProfileSummaries", []):
                    prof_id = prof.get("inferenceProfileId", "")
                    if not prof_id:
                        continue

                    pub, fam = _infer_bedrock_pub_and_family(prof_id, None)
                    has_vision = any(
                        k in prof_id.lower()
                        for k in ("image", "vision", "vl", "opus", "sonnet", "haiku", "fable", "nova", "pixtral", "scout", "maverick", "gpt-5.6", "gpt-6")
                    )
                    modalities = ["text"]
                    if has_vision:
                        modalities.append("image")
                    is_thinking = any(
                        k in prof_id.lower()
                        for k in ("thinking", "r1", "opus", "sonnet-4", "sonnet-5", "sonnet-3-7", "fable", "glm", "gpt-oss", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-6")
                    )
                    ctx = 1050000 if any(k in prof_id.lower() for k in ("gpt-5.6", "gpt-6")) else 200000 if "claude" in prof_id.lower() else 300000 if "nova" in prof_id.lower() else 128000

                    matched_cap = reg_by_trans.get(prof_id) or reg_by_id.get(f"bedrock-{prof_id.replace(':', '-').replace('.', '-')}")
                    in_cat = matched_cap is not None
                    is_cal = (matched_cap.verified if (matched_cap and matched_cap.enabled) else None) if in_cat else True
                    status = "callable" if (matched_cap and matched_cap.verified) else "registered" if in_cat else "available"

                    m_id = matched_cap.model_id if matched_cap else f"bedrock-{prof_id.replace(':', '-').replace('.', '-')}"
                    name = matched_cap.display_name if matched_cap else f"{prof.get('inferenceProfileName') or prof_id} (Bedrock)"

                    pricing = _estimate_bedrock_pricing(pub, fam, prof_id, card)

                    discovered_dict[prof_id] = DiscoveredModelOut(
                        model_id=m_id,
                        name=name,
                        provider="bedrock",
                        family=fam,
                        publisher=pub,
                        description=prof.get("description") or f"Inference profile for {pub.capitalize()} {fam.capitalize()} on AWS Bedrock ({target_region})",
                        is_registered=in_cat,
                        is_callable=is_cal,
                        region=target_region,
                        regions=[target_region],
                        capabilities={
                            "modalities": modalities,
                            "pdf_native": False,
                            "vision": has_vision,
                            "context_window": ctx,
                            "thinking": is_thinking,
                            "caching": pub == "anthropic",
                            "structured_method": "tools" if pub == "anthropic" else "json_mode",
                        },
                        pricing=pricing,
                        release_date=None,
                        status=status,
                    )
            except Exception:
                pass
        except Exception:
            pass

    # 2. Merge candidate models (ensures full baseline even offline or without IAM permissions)
    for item in _BEDROCK_CANDIDATES:
        mid = item["id"]
        trans = item.get("transport", mid)
        if trans not in discovered_dict:
            in_cat = is_registered(mid)
            cap = registry.get(mid)
            is_cal = cap.verified if (cap and cap.enabled) else None

            modalities = ["text"]
            if item.get("pdf"):
                modalities.append("pdf")
            if item.get("vision"):
                modalities.append("image")

            status = "registered" if in_cat else "available"
            if cap and cap.verified:
                status = "callable"
            elif in_cat and not (cap and cap.enabled):
                status = "unverified"

            discovered_dict[trans] = DiscoveredModelOut(
                model_id=mid,
                name=item["name"],
                provider="bedrock",
                family=item["family"],
                publisher=item["pub"],
                description=f"{item['pub'].capitalize()} {item['family'].capitalize()} model on AWS Bedrock ({target_region})",
                is_registered=in_cat,
                is_callable=is_cal,
                region=target_region,
                regions=[target_region],
                capabilities={
                    "modalities": modalities,
                    "pdf_native": bool(item.get("pdf")),
                    "vision": bool(item.get("vision")),
                    "context_window": item.get("ctx"),
                    "thinking": bool(item.get("thinking")),
                    "caching": item.get("pub") == "anthropic",
                    "structured_method": "tools" if item.get("pub") == "anthropic" else "json_mode",
                },
                pricing={
                    "input": item.get("in_m", 0.0),
                    "output": item.get("out_m", 0.0),
                    "input_per_million": item.get("in_m", 0.0),
                    "output_per_million": item.get("out_m", 0.0),
                    "cache_read_per_million": 0.3 if item.get("pub") == "anthropic" else None,
                    "thinking_per_million": item.get("out_m", 0.0) if item.get("thinking") else None,
                },
                release_date=item.get("rel"),
                status=status,
            )

    out_list = list(discovered_dict.values())

    # 3. Filter by query tokens if q is provided
    if q.strip():
        tokens = q.strip().lower().split()
        out_list = [
            m for m in out_list
            if all(
                tok in f"{m.model_id} {m.name} {m.family} {m.publisher} {m.description or ''}".lower()
                for tok in tokens
            )
        ]

    # 4. Sort: registered/callable models first, then publisher, then name
    def _sort_key(m: DiscoveredModelOut):
        priority = 0 if m.status == "callable" else 1 if m.is_registered else 2
        return (priority, m.publisher, m.name)

    out_list.sort(key=_sort_key)

    return DiscoverBedrockOut(
        total=len(out_list),
        has_credentials=has_creds,
        region=target_region,
        available_regions=[
            "us-east-1",
            "us-west-2",
            "ap-south-1",
            "eu-west-1",
            "us-east-2",
            "eu-central-1",
            "ap-southeast-1",
            "ap-northeast-1",
        ],
        discovered=out_list,
    )


@router.get("/regions", response_model=RegionsOut)
def get_available_regions() -> RegionsOut:
    """Return all supported cloud regions for Bedrock and Vertex AI."""
    settings = get_settings()
    active_bedrock = settings.aws_region_name or "us-east-1"
    active_vertex = settings.vertexai_location or "us-central1"

    bedrock_regions = [
        RegionInfo(id="us-east-1", name="US East (N. Virginia)", provider="bedrock", is_default=active_bedrock == "us-east-1"),
        RegionInfo(id="us-west-2", name="US West (Oregon)", provider="bedrock", is_default=active_bedrock == "us-west-2"),
        RegionInfo(id="ap-south-1", name="Asia Pacific (Mumbai)", provider="bedrock", is_default=active_bedrock == "ap-south-1"),
        RegionInfo(id="eu-west-1", name="Europe (Ireland)", provider="bedrock", is_default=active_bedrock == "eu-west-1"),
        RegionInfo(id="us-east-2", name="US East (Ohio)", provider="bedrock", is_default=active_bedrock == "us-east-2"),
        RegionInfo(id="eu-central-1", name="Europe (Frankfurt)", provider="bedrock", is_default=active_bedrock == "eu-central-1"),
        RegionInfo(id="ap-southeast-1", name="Asia Pacific (Singapore)", provider="bedrock", is_default=active_bedrock == "ap-southeast-1"),
        RegionInfo(id="ap-northeast-1", name="Asia Pacific (Tokyo)", provider="bedrock", is_default=active_bedrock == "ap-northeast-1"),
    ]

    vertex_regions = [
        RegionInfo(id="us-central1", name="Iowa (us-central1)", provider="vertex_ai", is_default=active_vertex == "us-central1"),
        RegionInfo(id="us-east4", name="N. Virginia (us-east4)", provider="vertex_ai", is_default=active_vertex == "us-east4"),
        RegionInfo(id="us-west1", name="Oregon (us-west1)", provider="vertex_ai", is_default=active_vertex == "us-west1"),
        RegionInfo(id="europe-west4", name="Netherlands (europe-west4)", provider="vertex_ai", is_default=active_vertex == "europe-west4"),
        RegionInfo(id="asia-east1", name="Taiwan (asia-east1)", provider="vertex_ai", is_default=active_vertex == "asia-east1"),
    ]

    return RegionsOut(
        bedrock=bedrock_regions,
        vertex_ai=vertex_regions,
        active_bedrock_region=active_bedrock,
        active_vertex_location=active_vertex,
    )


@router.post("/providers/bedrock/region")
def set_bedrock_region(payload: SetBedrockRegionIn) -> dict[str, Any]:
    """Change the active default Bedrock region."""
    reg = payload.region.strip().lower()
    settings = get_settings()
    settings.aws_region_name = reg
    os.environ["AWS_REGION_NAME"] = reg
    return {"region": reg, "updated": True}


@router.get("/providers/vertex/status")
def get_vertex_status() -> dict[str, Any]:
    """Check Vertex credentials and configuration status."""
    settings = get_settings()
    return {
        "has_credentials": settings.has_vertex_credentials,
        "project": settings.vertexai_project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        "location": settings.vertexai_location,
        "credentials_path": settings.google_application_credentials or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    }


@router.get("/providers/bedrock/status")
def get_bedrock_status() -> dict[str, Any]:
    """Check Bedrock credentials, token, and region configuration status."""
    settings = get_settings()
    token = settings.aws_bearer_token_bedrock or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    has_iam = bool(settings.aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID"))
    return {
        "has_credentials": bool(token or has_iam),
        "auth_mode": "IAM SigV4 (auto-renewing)" if has_iam else "Bearer token" if token else "None",
        "region": settings.aws_region_name or "us-east-1",
    }


@router.post("/models", response_model=CatalogModelOut)
async def add_model_to_catalog(payload: AddModelIn) -> CatalogModelOut:
    """Add or dynamically register a new model to the active catalog and rate card."""
    card = load_rate_card()
    model_id = payload.model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="Model ID cannot be empty")

    provider_str = payload.provider.lower()
    try:
        provider_enum = Provider(provider_str)
    except ValueError:
        provider_enum = Provider.vertex_ai if model_id.startswith("vertex_ai/") else Provider.openai_compatible

    modalities = {Modality.text}
    for m in payload.modalities:
        try:
            modalities.add(Modality(m.lower()))
        except ValueError:
            pass
    if payload.pdf_native:
        modalities.add(Modality.pdf)
    if payload.vision:
        modalities.add(Modality.image)

    structured_method = StructuredMethod.json_schema
    try:
        structured_method = StructuredMethod(payload.structured_method)
    except ValueError:
        pass

    pricing_ref = f"dyn:{model_id}"
    register_dynamic_model(
        pricing_ref,
        {
            "input_usd_per_million": payload.input_per_million,
            "output_usd_per_million": payload.output_per_million,
            "thinking_usd_per_million": payload.output_per_million if payload.thinking else None,
        },
    )

    cap = ModelCapability(
        model_id=model_id,
        litellm_model=model_id,
        display_name=payload.display_name.strip() or model_id,
        provider=provider_enum,
        access=Access.maas if payload.access == "maas" else Access.self_deploy,
        modalities=frozenset(modalities),
        pdf_native=payload.pdf_native,
        vision=payload.vision,
        context_window=payload.context_window,
        structured_method=structured_method,
        needs_repair_fallback=structured_method == StructuredMethod.json_mode,
        thinking=payload.thinking,
        caching=payload.caching,
        batch=payload.batch,
        pricing_ref=pricing_ref,
        enabled=payload.enabled,
        verified=False,
        notes=payload.notes,
    )

    meta = {
        "family": payload.family or provider_str,
        "version": "custom",
        "variant": "custom",
        "reason": None,
    }

    # If verify_now requested, attempt live verification
    if payload.verify_now:
        try:
            verifier = _load_verify()
            register_model(cap, meta)
            ok = bool(await verifier(model_id))
            if ok:
                cap = cap.model_copy(update={"verified": True, "enabled": True})
        except Exception:
            # Keep registered with verified=False
            pass

    register_model(cap, meta)
    save_custom_model_to_disk(
        cap,
        meta,
        {
            "input_usd_per_million": payload.input_per_million,
            "output_usd_per_million": payload.output_per_million,
            "thinking_usd_per_million": payload.output_per_million if payload.thinking else None,
        },
    )
    return _catalog_row(model_id, card)


@router.delete("/models/{model_id:path}")
def delete_model_from_catalog(model_id: str) -> dict[str, bool]:
    """Remove a dynamic model from active catalog."""
    from urllib.parse import unquote

    raw_id = unquote(model_id)
    delete_custom_model_from_disk(raw_id)
    removed = unregister_model(raw_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Model '{raw_id}' not found in registry")
    return {"deleted": True}


@router.get("/search")
def search_all_catalog_models(
    q: str = "",
    provider: str = "",
    modality: str = "",
    region: str = "",
    limit: int = 100,
) -> dict:
    """Search all catalog models across all providers with optional text, provider, modality, and region filters."""
    card = load_rate_card()
    all_rows = [_catalog_row(cap.model_id, card) for cap in list_models()]
    query = q.strip().lower()
    prov = provider.strip().lower()
    mod = modality.strip().lower()
    reg = region.strip().lower()

    filtered = []
    for row in all_rows:
        if prov and row.provider.lower() != prov:
            continue
        if mod == "vision" and not row.capabilities.get("vision"):
            continue
        if mod == "pdf" and not row.capabilities.get("pdf_native"):
            continue
        if mod == "thinking" and not row.capabilities.get("thinking"):
            continue
        if reg:
            model_reg = (row.region or "").lower()
            model_regs = [r.lower() for r in (row.regions or [])]
            match_reg = reg in model_reg or any(reg in r for r in model_regs)
            if not match_reg:
                # Check nicknames
                nicks = _REGION_NICKNAMES.get(model_reg, [])
                if not any(reg in n for n in nicks):
                    continue

        if query:
            model_reg = (row.region or "").lower()
            model_regs = [r.lower() for r in (row.regions or [])]
            reg_nicks = _REGION_NICKNAMES.get(model_reg, [])
            searchable = f"{row.id} {row.name} {row.provider} {row.family} {model_reg} {' '.join(model_regs)} {' '.join(reg_nicks)}".lower()
            tokens = query.split()
            if not all(tok in searchable for tok in tokens):
                continue
        filtered.append(row.model_dump(mode="json"))

    return {"total": len(filtered), "models": filtered[: max(1, limit)]}


@router.get("/openrouter/search")
def search_openrouter(q: str = "", vendor: str = "", free: bool = False, limit: int = 50) -> dict:
    """Search the live OpenRouter catalog (~345 models) so the UI can pick any of them.

    Returns rows shaped like ``/catalog`` models (id/name/provider/pricing/capabilities) so the
    frontend can drop them straight into the picker. Any id returned here is directly runnable —
    the registry resolves ``openrouter/*`` ids dynamically.
    """
    from app.providers.openrouter import search_models

    try:
        matches = search_models(q or None, vendor=vendor or None, free_only=free)
    except Exception as exc:  # offline / rate-limited -> empty result, not a 500
        raise HTTPException(status_code=502, detail=f"OpenRouter unavailable: {exc}") from exc

    rows = [
        {
            "id": m.colosseum_id,
            "model_id": m.colosseum_id,
            "name": f"{m.name} (OpenRouter)",
            "provider": "openrouter",
            "family": "openrouter",
            "enabled": True,
            "verified": False,
            "gate_reason": None,
            "release_date": m.release_date,
            "capabilities": {
                "modalities": list(m.modalities),
                "pdf_native": any(modality in {"file", "pdf"} for modality in m.modalities),
                "vision": "image" in m.modalities,
                "structured_method": "json_mode",
                "thinking": False,
                "caching": False,
                "batch": False,
                "context_window": m.context_length,
            },
            "pricing": {
                "input": float(m.input_usd_per_million),
                "output": float(m.output_usd_per_million),
                "input_per_million": float(m.input_usd_per_million),
                "output_per_million": float(m.output_usd_per_million),
                "cache_read_per_million": None,
                "thinking_per_million": None,
            },
        }
        for m in matches
    ]
    return {"total": len(rows), "models": rows[: max(1, limit)]}


def _load_verify():
    path = REPO_ROOT / "scripts" / "verify_model.py"
    spec = importlib.util.spec_from_file_location("colosseum_verify_model", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/verify_model.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify


@router.post("/{model_id:path}/verify", response_model=VerifyOut)
async def verify_model(model_id: str) -> VerifyOut:
    from urllib.parse import unquote

    from app.providers.registry import get_capability

    raw_id = unquote(model_id)
    try:
        capability = get_capability(raw_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Model not found") from None
    started = time.perf_counter()
    try:
        ok = bool(await _load_verify()(raw_id))
        error = None if ok else "Model verification returned an invalid response"
    except Exception as exc:  # provider failures belong in the response, not a 500 page
        ok = False
        error = str(exc)
    elapsed = int((time.perf_counter() - started) * 1000)
    snippet = None
    if ok:
        registry[raw_id] = capability.model_copy(update={"enabled": True, "verified": True})
        snippet = f"model_id: {raw_id}\nenabled: true\nverified: true"
    else:
        raise HTTPException(status_code=400, detail=error)
    return VerifyOut(ok=ok, error=error, latency_ms=elapsed, yaml_snippet=snippet)

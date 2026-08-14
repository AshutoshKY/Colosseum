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
    DiscoverVertexOut,
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
def discover_vertex_models() -> DiscoverVertexOut:
    """Discover available Vertex AI & Partner Model Garden models and check live readiness."""
    settings = get_settings()
    has_creds = settings.has_vertex_credentials
    project = settings.vertexai_project or os.environ.get("GOOGLE_CLOUD_PROJECT") or "vertex-internal-testing"
    location = settings.vertexai_location or "us-central1"

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
                description=f"{item['pub'].capitalize()} {item['family'].capitalize()} model on Vertex Model Garden",
                is_registered=in_cat,
                is_callable=is_cal,
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
        location=location,
        discovered=out_list,
    )


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

"""Model catalog metadata and opt-in live verification."""

from __future__ import annotations

import importlib.util
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.schemas import CatalogModelOut, CatalogOut, VerifyOut
from app.providers.pricing.estimator import load_rate_card, resolve_pricing_ref
from app.providers.registry import (
    catalog_meta,
    catalog_summary,
    gate_reason,
    list_models,
    registry,
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
    return CatalogModelOut(
        id=model_id,
        model_id=model_id,
        name=capability.display_name,
        provider=capability.provider.value,
        family=str(meta.get("family") or "unknown"),
        enabled=capability.enabled,
        verified=capability.verified,
        gate_reason=gate_reason(model_id),
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
    capability = registry.get(model_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Model not found")
    started = time.perf_counter()
    try:
        ok = bool(await _load_verify()(model_id))
        error = None if ok else "Model verification returned an invalid response"
    except Exception as exc:  # provider failures belong in the response, not a 500 page
        ok = False
        error = str(exc)
    elapsed = int((time.perf_counter() - started) * 1000)
    snippet = None
    if ok:
        registry[model_id] = capability.model_copy(update={"enabled": True, "verified": True})
        snippet = f"model_id: {model_id}\nenabled: true\nverified: true"
    else:
        raise HTTPException(status_code=400, detail=error)
    return VerifyOut(ok=ok, error=error, latency_ms=elapsed, yaml_snippet=snippet)

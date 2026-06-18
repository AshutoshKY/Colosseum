"""Cost estimator — multi-provider, thinking + cache aware.

Extends superclaims-ai's ``estimated_vertex_cost`` to: (a) work off canonical
``NormalizedUsage`` rather than a raw provider blob, (b) price reasoning/thinking tokens
with a dedicated rate, and (c) support a regional multiplier (e.g. Claude on Vertex's
+10% premium) recorded per-run for fair cost comparison.

Pricing keys come from each model's ``pricing_ref`` in the registry.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from app.providers.usage import NormalizedUsage

_RATE_CARD_PATH = Path(__file__).resolve().parent / "rate_card.json"
_MILLION = Decimal("1000000")


@dataclass(frozen=True)
class EstimatedCost:
    input_usd: Decimal
    output_usd: Decimal
    cache_usd: Decimal
    thinking_usd: Decimal
    total_usd: Decimal
    pricing_version: str
    pricing_ref: str | None


def load_rate_card() -> dict[str, Any]:
    override = os.getenv("COLOSSEUM_RATE_CARD_JSON", "").strip()
    if override:
        return cast(dict[str, Any], json.loads(override))
    return cast(dict[str, Any], json.loads(_RATE_CARD_PATH.read_text(encoding="utf-8")))


def resolve_pricing_ref(pricing_ref: str | None, card: dict[str, Any]) -> str | None:
    """Resolve an alias chain + prefix-match a pricing_ref to a rate-card model key."""
    if not pricing_ref:
        return None
    key = pricing_ref.strip().lower()
    aliases = card.get("aliases") or {}
    seen: set[str] = set()
    while key in aliases and key not in seen:
        seen.add(key)
        key = str(aliases[key]).lower()
    models = cast(dict[str, Any], card.get("models") or {})
    if key in models:
        return key
    for candidate in sorted(models.keys(), key=len, reverse=True):
        if key == candidate or key.startswith(f"{candidate}-") or key.startswith(f"{candidate}."):
            return candidate
    return None


def _region_multiplier(card: dict[str, Any], region: str | None) -> Decimal:
    multipliers = card.get("region_multipliers") or {}
    key = (region or "default").lower()
    return Decimal(str(multipliers.get(key, multipliers.get("default", 1.0))))


def estimate_cost(
    *,
    pricing_ref: str | None,
    usage: NormalizedUsage,
    region: str | None = None,
    rate_card: dict[str, Any] | None = None,
) -> EstimatedCost:
    """Estimate USD cost for one call from canonical usage + the model's pricing_ref."""
    card = rate_card or load_rate_card()
    version = str(card.get("version", "unknown"))
    resolved = resolve_pricing_ref(pricing_ref, card)
    rates = (card.get("models") or {}).get(resolved) if resolved else None
    mult = _region_multiplier(card, region)

    zero = Decimal("0")
    if not rates:
        return EstimatedCost(zero, zero, zero, zero, zero, version, resolved)

    input_rate = Decimal(str(rates.get("input_usd_per_million", 0)))
    output_rate = Decimal(str(rates.get("output_usd_per_million", 0)))
    cache_rate = Decimal(str(rates.get("cache_read_usd_per_million", input_rate)))
    thinking_rate = Decimal(str(rates.get("thinking_usd_per_million", output_rate)))

    uncached_input = max(0, usage.input_tokens - usage.cached_tokens)

    input_usd = Decimal(uncached_input) / _MILLION * input_rate * mult
    cache_usd = Decimal(usage.cached_tokens) / _MILLION * cache_rate * mult
    output_usd = Decimal(usage.output_tokens) / _MILLION * output_rate * mult
    thinking_usd = Decimal(usage.thinking_tokens) / _MILLION * thinking_rate * mult
    total_usd = input_usd + cache_usd + output_usd + thinking_usd

    return EstimatedCost(
        input_usd=input_usd,
        output_usd=output_usd,
        cache_usd=cache_usd,
        thinking_usd=thinking_usd,
        total_usd=total_usd,
        pricing_version=version,
        pricing_ref=resolved,
    )

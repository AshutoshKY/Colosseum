"""OpenRouter model discovery.

OpenRouter fronts ~345 upstream models across ~56 vendors — far too many to hand-curate into
``catalog/openrouter.yaml`` (which carries only a verified, always-on subset). This module hits
OpenRouter's live ``/models`` endpoint so callers can *search* the full catalog, inspect pricing
and context windows, and mint the ``openrouter/<vendor>/<model>`` id / ``litellm_model`` transport
for any model without editing the YAML.

Usage (CLI)::

    python -m app.providers.openrouter --search gpt          # name/id substring
    python -m app.providers.openrouter --vendor anthropic    # all Anthropic models
    python -m app.providers.openrouter --free                # $0 models
    python -m app.providers.openrouter --limit 20            # cap rows

Any id printed here (``openrouter/<vendor>/<model>``) is directly usable as ``model_id`` /
``litellm_model`` — the gateway routes it through the ``openrouter`` provider path with
``OPENROUTER_API_KEY``. The endpoint is public; the key is only needed to *invoke* a model.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from app.providers.capabilities import ModelCapability

from datetime import datetime, timezone

_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class OpenRouterModel:
    """One model as advertised by OpenRouter's ``/models`` endpoint."""

    id: str  # e.g. "openai/gpt-4o"
    name: str
    context_length: int | None
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    modalities: tuple[str, ...]
    created: int | None = None

    @property
    def vendor(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def colosseum_id(self) -> str:
        """The id Colosseum uses as ``model_id`` / ``litellm_model``."""
        return f"openrouter/{self.id}"

    @property
    def is_free(self) -> bool:
        return self.input_usd_per_million == 0 and self.output_usd_per_million == 0

    @property
    def release_date(self) -> str | None:
        if not self.created:
            return None
        try:
            return datetime.fromtimestamp(self.created, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return None


def _to_per_million(raw: object) -> Decimal:
    try:
        return Decimal(str(raw)) * Decimal(1_000_000)
    except Exception:  # noqa: BLE001 — malformed/absent price -> treat as unknown/free
        return Decimal(0)


def fetch_models(*, timeout: float = 20.0) -> list[OpenRouterModel]:
    """Fetch the full live OpenRouter model catalog (no API key required)."""
    req = urllib.request.Request(_MODELS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
        payload = json.load(resp)
    out: list[OpenRouterModel] = []
    for m in payload.get("data", []):
        pricing = m.get("pricing") or {}
        arch = m.get("architecture") or {}
        out.append(
            OpenRouterModel(
                id=m["id"],
                name=m.get("name", m["id"]),
                context_length=m.get("context_length"),
                input_usd_per_million=_to_per_million(pricing.get("prompt")),
                output_usd_per_million=_to_per_million(pricing.get("completion")),
                modalities=tuple(arch.get("input_modalities") or ["text"]),
                created=m.get("created"),
            )
        )
    return out


def search_models(
    query: str | None = None,
    *,
    vendor: str | None = None,
    free_only: bool = False,
    models: list[OpenRouterModel] | None = None,
) -> list[OpenRouterModel]:
    """Filter the OpenRouter catalog by id/name substring, vendor, and/or free pricing."""
    pool = models if models is not None else fetch_models()
    q = (query or "").strip().lower()
    v = (vendor or "").strip().lower()
    results = [
        m
        for m in pool
        if (not q or q in m.id.lower() or q in m.name.lower())
        and (not v or m.vendor == v)
        and (not free_only or m.is_free)
    ]
    return sorted(results, key=lambda m: m.id)


# --------------------------------------------------------------------------- dynamic registry
# The curated ``catalog/openrouter.yaml`` holds only a verified subset; OpenRouter serves ~345
# models. Rather than hand-list them all, we let *any* ``openrouter/<vendor>/<model>`` id resolve
# to a synthesized capability (text-only, json_mode + repair ladder, priced from the live
# ``/models`` feed). This is what makes the FE search + "add any model" flow runnable.

_CACHE_TTL_S = 600.0
_cache: dict[str, object] = {"at": 0.0, "by_id": {}}


def fetch_models_cached(*, ttl: float = _CACHE_TTL_S) -> dict[str, OpenRouterModel]:
    """``{openrouter_id: OpenRouterModel}`` for the full live catalog, cached for ``ttl`` s.

    ``openrouter_id`` is the Colosseum id (``openrouter/<vendor>/<model>``). Network/parse
    failures return the last good cache (possibly empty) so callers degrade gracefully.
    """
    import time

    now = time.time()
    by_id = cast("dict[str, OpenRouterModel]", _cache["by_id"])
    if by_id and (now - cast(float, _cache["at"])) < ttl:
        return by_id
    try:
        fresh = {m.colosseum_id: m for m in fetch_models()}
    except Exception:  # noqa: BLE001 — offline / rate-limited: keep last good cache
        return by_id
    _cache["by_id"] = fresh
    _cache["at"] = now
    return fresh


def lookup(model_id: str) -> OpenRouterModel | None:
    """Find a live OpenRouter model by its Colosseum id (``openrouter/<vendor>/<model>``)."""
    return fetch_models_cached().get(model_id)


def synthesize_capability(model_id: str) -> ModelCapability | None:
    """Build a runnable ``ModelCapability`` for any live ``openrouter/*`` id, or ``None``.

    The live catalog supplies input modalities.  Models advertising image or file/PDF input are
    allowed to receive documents; other models remain text-only.  Pricing is injected into the
    in-memory rate card under a synthetic ``openrouter-dyn:<id>`` ref.
    """
    from app.providers.capabilities import (
        Access,
        Modality,
        ModelCapability,
        Provider,
        StructuredMethod,
    )

    if not model_id.startswith("openrouter/"):
        return None
    live = lookup(model_id)
    if live is None:
        return None

    pricing_ref = _register_dynamic_pricing(live)
    input_modalities = {item.lower() for item in live.modalities}
    supports_images = "image" in input_modalities
    supports_pdf = bool({"file", "pdf"} & input_modalities)
    modalities = {Modality.text}
    if supports_images:
        modalities.add(Modality.image)
    if supports_pdf:
        modalities.add(Modality.pdf)
    return ModelCapability(
        model_id=live.colosseum_id,
        litellm_model=live.colosseum_id,
        display_name=f"{live.name} (OpenRouter)",
        provider=Provider.openrouter,
        access=Access.maas,
        modalities=frozenset(modalities),
        pdf_native=supports_pdf,
        vision=supports_images,
        context_window=live.context_length,
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        thinking=False,
        api_key_env="OPENROUTER_API_KEY",
        pricing_ref=pricing_ref,
        enabled=True,
        verified=False,
        release_date=live.release_date,
        notes="Dynamically resolved from the live OpenRouter catalog (not hand-curated).",
    )


def _register_dynamic_pricing(live: OpenRouterModel) -> str:
    """Register this model's live per-M pricing in the runtime overlay; return its ref key."""
    from app.providers.pricing.estimator import register_dynamic_model

    ref = f"openrouter-dyn:{live.id}"
    register_dynamic_model(
        ref,
        {
            "input_usd_per_million": float(live.input_usd_per_million),
            "output_usd_per_million": float(live.output_usd_per_million),
        },
    )
    return ref


def check_key(*, api_key: str | None = None) -> tuple[bool, str]:
    """Verify ``OPENROUTER_API_KEY`` can authenticate (via the credits endpoint)."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return False, "OPENROUTER_API_KEY not set"
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            data = json.load(resp).get("data", {})
        total = data.get("total_credits")
        used = data.get("total_usage")
        remaining = (total - used) if (total is not None and used is not None) else None
        return True, f"OK — credits remaining: {remaining}"
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return False, f"auth failed: HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"error: {exc.__class__.__name__}: {exc}"


def _main() -> None:
    ap = argparse.ArgumentParser(description="Search the live OpenRouter model catalog.")
    ap.add_argument("--search", help="id/name substring, e.g. 'gpt', 'sonnet', 'vision'")
    ap.add_argument("--vendor", help="exact vendor prefix, e.g. 'openai', 'anthropic', 'qwen'")
    ap.add_argument("--free", action="store_true", help="only $0 (free) models")
    ap.add_argument("--limit", type=int, default=40, help="max rows to print (default 40)")
    ap.add_argument("--check-key", action="store_true", help="verify OPENROUTER_API_KEY auth")
    args = ap.parse_args()

    if args.check_key:
        ok, msg = check_key()
        print(("✓ " if ok else "✗ ") + msg)

    all_models = fetch_models()
    results = search_models(args.search, vendor=args.vendor, free_only=args.free, models=all_models)
    shown = results[: args.limit]

    print(f"\n{len(all_models)} models on OpenRouter — {len(results)} match; showing {len(shown)}:\n")
    print(f"  {'colosseum model_id':52} {'ctx':>9}  {'in$/M':>7} {'out$/M':>7}")
    print(f"  {'-' * 52} {'-' * 9}  {'-' * 7} {'-' * 7}")
    for m in shown:
        ctx = f"{m.context_length:,}" if m.context_length else "-"
        print(
            f"  {m.colosseum_id:52} {ctx:>9}  "
            f"{float(m.input_usd_per_million):>7.3f} {float(m.output_usd_per_million):>7.3f}"
        )
    if len(results) > len(shown):
        print(f"\n  … {len(results) - len(shown)} more (raise --limit)")


if __name__ == "__main__":
    _main()

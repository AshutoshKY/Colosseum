"""Model capability registry — loaded from the data-driven catalog (``providers/catalog/``).

The catalog YAML files are the single source of truth and are kept in sync with
``docs/models-and-caveats.md``. This module materializes them into ``ModelCapability`` objects
and exposes lookup/listing helpers.

**Availability gating (critical):** a model is ``enabled=True`` ONLY when the catalog marks it
verified callable on this project's Vertex (or it has a working external key). Everything else
is registered ``enabled=False, verified=False`` with a ``reason`` (folded into ``notes``). The
live smoke (``runner.opd_smoke``) probes the gated-off Model-Garden models and, for any that
actually answer, records a verification override so later runs can enable them — but we never
ship an unverified capability flag as enabled by default.

**Verified + enabled (June 2026):** only the Gemini family on ``vertex-internal-testing`` is
confirmed callable. Every other family is registered disabled with the reason it is gated off
(Model-Garden enablement unconfirmed without ``gcloud``, or no external API key).
"""

from __future__ import annotations

from collections import defaultdict

from app.providers.capabilities import ModelCapability, Provider
from app.providers.catalog import load_catalog

# model_id -> capability ; model_id -> grouping metadata (family/version/variant/reason)
registry: dict[str, ModelCapability] = {}
catalog_meta: dict[str, dict] = {}

for _cap, _meta in load_catalog():
    registry[_cap.model_id] = _cap
    catalog_meta[_cap.model_id] = _meta


def get_capability(model_id: str) -> ModelCapability:
    """Return the capability profile for ``model_id`` or raise ``KeyError``.

    Static catalog entries win. Any other ``openrouter/*`` id is resolved *dynamically* from the
    live OpenRouter catalog (text-only, json_mode + repair ladder, priced from the live feed) and
    cached, so users can pick from OpenRouter's full ~345-model fleet via search without a YAML
    edit. Resolved dynamic capabilities are memoized into the registry.
    """
    cap = registry.get(model_id)
    if cap is not None:
        return cap

    if model_id.startswith("openrouter/"):
        from app.providers.openrouter import synthesize_capability

        dynamic = synthesize_capability(model_id)
        if dynamic is not None:
            registry[model_id] = dynamic
            catalog_meta[model_id] = {
                "family": "openrouter",
                "version": model_id.split("/")[-1],
                "variant": "dynamic",
                "reason": None,
            }
            return dynamic

    raise KeyError(  # noqa: TRY003
        f"Model '{model_id}' is not in the registry. "
        f"Add it to a providers/catalog/*.yaml file and docs/models-and-caveats.md first."
    )


def is_registered(model_id: str) -> bool:
    return model_id in registry


def list_models(
    *,
    enabled_only: bool = False,
    provider: Provider | None = None,
    family: str | None = None,
) -> list[ModelCapability]:
    caps = list(registry.values())
    if enabled_only:
        caps = [c for c in caps if c.enabled]
    if provider is not None:
        caps = [c for c in caps if c.provider == provider]
    if family is not None:
        caps = [c for c in caps if catalog_meta.get(c.model_id, {}).get("family") == family]
    return caps


def families() -> dict[str, list[ModelCapability]]:
    """Group registered capabilities by their catalog ``family``."""
    out: dict[str, list[ModelCapability]] = defaultdict(list)
    for cap in registry.values():
        fam = catalog_meta.get(cap.model_id, {}).get("family", "unknown")
        out[fam].append(cap)
    return dict(out)


def catalog_summary() -> dict[str, dict[str, int]]:
    """Per-family counts: total / enabled / gated-off (for the Phase-2 report)."""
    summary: dict[str, dict[str, int]] = {}
    for fam, caps in families().items():
        enabled = sum(1 for c in caps if c.enabled)
        summary[fam] = {"total": len(caps), "enabled": enabled, "gated_off": len(caps) - enabled}
    return summary


def gate_reason(model_id: str) -> str | None:
    """Why a model is gated off (``None`` if enabled)."""
    cap = registry.get(model_id)
    if cap is None or cap.enabled:
        return None
    return catalog_meta.get(model_id, {}).get("reason")


def register_model(capability: ModelCapability, meta: dict | None = None) -> None:
    """Register or update a model capability profile at runtime."""
    registry[capability.model_id] = capability
    catalog_meta[capability.model_id] = meta or {
        "family": capability.provider.value,
        "version": "custom",
        "variant": "custom",
        "reason": None,
    }


def unregister_model(model_id: str) -> bool:
    """Unregister a dynamic model profile if present."""
    if model_id in registry:
        del registry[model_id]
        catalog_meta.pop(model_id, None)
        return True
    return False

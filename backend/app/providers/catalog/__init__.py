"""Data-driven model catalog loader.

The catalog lives as declarative YAML files in this package (one per family), grouped
``family -> version -> variant``. ``load_catalog()`` reads every ``*.yaml`` and materializes
``ModelCapability`` objects with each model's full capability profile + availability gate
(``enabled``/``verified``/``reason``).

This is the single source feeding ``providers/registry.py`` and is documented in
``docs/models-and-caveats.md`` (the two must stay in sync). A model is ``enabled=True`` ONLY
when verified callable on this project's Vertex (or has a working external key); everything
else ships ``enabled=False, verified=False`` with a ``reason``.

Schema (per file):
  family: <str>
  # EITHER a single group inline ...
  provider: <Provider>     access: <Access>     defaults: {<capability fields>}     models: [ ... ]
  # ... OR multiple groups (e.g. a family on Vertex MaaS AND an external API):
  groups: [ { provider, access, defaults, models }, ... ]

Each ``models`` entry carries ``model_id`` + grouping keys (``version``/``variant``) and may
override any capability field from its group's ``defaults``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.providers.capabilities import (
    Access,
    Modality,
    ModelCapability,
    Provider,
    StructuredMethod,
)

_CATALOG_DIR = Path(__file__).resolve().parent

# Capability fields that may be set in a group's ``defaults`` or overridden per-model.
_CAPABILITY_FIELDS = {
    "litellm_model",
    "modalities",
    "pdf_native",
    "vision",
    "max_image_mb",
    "max_payload_mb",
    "max_image_megapixels",
    "image_formats",
    "context_window",
    "structured_method",
    "needs_repair_fallback",
    "thinking",
    "caching",
    "batch",
    "pricing_ref",
    "enabled",
    "verified",
    "notes",
    "base_url_env",
    "api_key_env",
    "vertex_location",
}


def _coerce(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field == "modalities":
        return frozenset(Modality(m) for m in value)
    if field == "image_formats":
        return frozenset(str(f).lower() for f in value)
    if field == "structured_method":
        return StructuredMethod(value)
    return value


def _build_capability(
    *, model: dict[str, Any], provider: Provider, access: Access, defaults: dict[str, Any]
) -> tuple[ModelCapability, dict[str, Any]]:
    """Merge group defaults with per-model overrides into a ``ModelCapability``.

    Returns the capability plus its catalog grouping metadata (family/version/variant/reason).
    """
    merged: dict[str, Any] = {}
    for field in _CAPABILITY_FIELDS:
        if field in model:
            merged[field] = _coerce(field, model[field])
        elif field in defaults:
            merged[field] = _coerce(field, defaults[field])

    cap = ModelCapability(
        model_id=model["model_id"],
        display_name=model["display_name"],
        provider=provider,
        access=access,
        **merged,
    )
    meta = {
        "family": model.get("_family"),
        "version": model.get("version"),
        "variant": model.get("variant"),
        # ``reason`` is the gate explanation; it is not a ModelCapability field, so it travels
        # in metadata and is surfaced via notes when the model is disabled.
        "reason": model.get("reason") or defaults.get("reason"),
    }
    return cap, meta


def _iter_groups(doc: dict[str, Any]):
    family = doc.get("family", "unknown")
    if "groups" in doc:
        for group in doc["groups"]:
            yield family, group
    else:
        yield family, doc


def load_catalog() -> list[tuple[ModelCapability, dict[str, Any]]]:
    """Load every catalog YAML into ``(ModelCapability, grouping_meta)`` pairs."""
    out: list[tuple[ModelCapability, dict[str, Any]]] = []
    for path in sorted(_CATALOG_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not doc:
            continue
        for family, group in _iter_groups(doc):
            provider = Provider(group["provider"])
            access = Access(group.get("access", "maas"))
            defaults = group.get("defaults", {}) or {}
            for model in group.get("models", []) or []:
                model = {**model, "_family": family}
                cap, meta = _build_capability(
                    model=model,
                    provider=Provider(model.get("provider", provider)),
                    access=Access(model.get("access", access)),
                    defaults=defaults,
                )
                # When a model is gated off, fold the reason into notes so it persists on the
                # model_catalog row + shows up in the registry without a separate field.
                if not cap.enabled and meta["reason"]:
                    note = cap.notes or ""
                    cap = cap.model_copy(
                        update={"notes": (f"DISABLED: {meta['reason']}. " + note).strip()}
                    )
                out.append((cap, meta))
    return out


__all__ = ["load_catalog"]

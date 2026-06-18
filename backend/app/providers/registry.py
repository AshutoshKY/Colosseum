"""Model capability registry — generated to match ``docs/models-and-caveats.md``.

Source of truth is the seed caveats table in that doc. Cells marked **(verify)** there are
encoded conservatively here: the model ships ``enabled=False`` / ``verified=False`` and the
risky capability (vision/pdf) is left off until confirmed live against provider docs.

**Verified for Phase 1 (June 2026):** only the Gemini family is confirmed and enabled. Per
the build constraints, every other provider is stubbed as disabled so the plug-and-play seam
exists without shipping unverified capability flags.
"""

from __future__ import annotations

from app.providers.capabilities import (
    Access,
    Modality,
    ModelCapability,
    Provider,
    StructuredMethod,
)

# --- canonical modality sets ---
_TEXT = frozenset({Modality.text})
_TEXT_IMAGE = frozenset({Modality.text, Modality.image})
_TEXT_IMAGE_PDF = frozenset({Modality.text, Modality.image, Modality.pdf})

# Vertex cross-cutting payload cap (docs: 30 MB request payload).
_VERTEX_PAYLOAD_MB = 30.0


def _gemini(model_id: str, display_name: str, pricing_ref: str) -> ModelCapability:
    """Gemini-on-Vertex profile. VERIFIED June 2026 against Vertex AI docs:
    native PDF, vision, json_schema structured output, ~1M context, thinking + caching.
    """
    return ModelCapability(
        model_id=model_id,
        display_name=display_name,
        provider=Provider.vertex_ai,
        access=Access.maas,
        modalities=_TEXT_IMAGE_PDF,
        pdf_native=True,
        vision=True,
        max_payload_mb=_VERTEX_PAYLOAD_MB,
        context_window=1_000_000,
        structured_method=StructuredMethod.json_schema,
        thinking=True,
        caching=True,
        batch=True,
        pricing_ref=pricing_ref,
        enabled=True,
        verified=True,
    )


# =============================================================================
# VERIFIED + ENABLED (Phase 1): Gemini on Vertex AI
# =============================================================================
_GEMINI: list[ModelCapability] = [
    _gemini("vertex_ai/gemini-2.5-flash", "Gemini 2.5 Flash", "gemini-2.5-flash"),
    _gemini("vertex_ai/gemini-2.5-pro", "Gemini 2.5 Pro", "gemini-2.5-pro"),
    _gemini("vertex_ai/gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "gemini-2.5-flash-lite"),
    _gemini("vertex_ai/gemini-3-flash-preview", "Gemini 3 Flash", "gemini-3-flash-preview"),
    _gemini("vertex_ai/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "gemini-3.1-pro-preview"),
    _gemini("vertex_ai/gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "gemini-3.1-flash-lite"),
]


# =============================================================================
# STUBBED (disabled until verified live) — Phase 2 enables these after verifying
# each (verify) cell from docs/models-and-caveats.md against current provider docs.
# Capabilities are encoded conservatively; the risky flag is OFF where the doc says (verify).
# =============================================================================
_STUBS: list[ModelCapability] = [
    # Claude on Vertex (vertex_partner). Native PDF + vision + caching + tools; +10% regional
    # premium recorded per-run via run_result.endpoint. Disabled until Phase 2 verifies.
    ModelCapability(
        model_id="vertex_ai/claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6 (Vertex)",
        provider=Provider.vertex_partner,
        modalities=_TEXT_IMAGE_PDF,
        pdf_native=True,
        vision=True,
        max_payload_mb=_VERTEX_PAYLOAD_MB,
        structured_method=StructuredMethod.tools,
        thinking=True,
        caching=True,
        pricing_ref="claude-sonnet-4-6",
        enabled=False,
        verified=False,
        notes="(verify) +10% regional/multi-region premium; record endpoint for fair cost compare.",
    ),
    # Mistral Small 3.1 — multimodal via image; SO method (verify).
    ModelCapability(
        model_id="vertex_ai/mistral-small-2503",
        display_name="Mistral Small 3.1 (Vertex)",
        provider=Provider.vertex_partner,
        modalities=_TEXT_IMAGE,
        pdf_native=False,
        vision=True,
        max_payload_mb=_VERTEX_PAYLOAD_MB,
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        pricing_ref="mistral-small",
        enabled=False,
        verified=False,
        notes="(verify) structured-output method; PDF via rasterized images.",
    ),
    # DeepSeek R1 — TEXT ONLY. Capability gate must skip image/PDF tasks (record N/A).
    ModelCapability(
        model_id="vertex_ai/deepseek-r1",
        display_name="DeepSeek R1 (Vertex)",
        provider=Provider.vertex_partner,
        modalities=_TEXT,
        pdf_native=False,
        vision=False,
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        thinking=True,
        pricing_ref="deepseek-r1",
        enabled=False,
        verified=False,
        notes="text-only: gate out of image/PDF tasks; (verify) json mode reliability.",
    ),
    # Qwen3 base — text-only; use the VL variant for vision. SO (verify).
    ModelCapability(
        model_id="vertex_ai/qwen3",
        display_name="Qwen3 (Vertex)",
        provider=Provider.vertex_partner,
        modalities=_TEXT,
        pdf_native=False,
        vision=False,
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        pricing_ref="qwen3",
        enabled=False,
        verified=False,
        notes="base Qwen3 text-only; use VL variant for vision. (verify) SO method.",
    ),
    # Grok 4.x (xAI). VISION caveats are HARD: base64 <=4 MB, <=33 MP, jpg/png only, tiled billing.
    # PDFs MUST be rasterized per page. Disabled until Phase 2 verifies SO method live.
    ModelCapability(
        model_id="xai/grok-4",
        display_name="Grok 4 (xAI)",
        provider=Provider.xai,
        modalities=_TEXT_IMAGE,
        pdf_native=False,
        vision=True,
        max_image_mb=4.0,
        max_image_megapixels=33.0,
        image_formats=frozenset({"jpeg", "png"}),
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        thinking=True,
        pricing_ref="grok-4",
        enabled=False,
        verified=False,
        notes="base64 image <=4 MB, URL <=20 MB, <=33 MP, jpg/png only, tile-based billing. "
        "(verify) structured-output method.",
    ),
    # GLM 5.x — VL only (verify); modality + SO unverified.
    ModelCapability(
        model_id="openai_compatible/glm-5",
        display_name="GLM 5 (Zhipu)",
        provider=Provider.openai_compatible,
        modalities=_TEXT,
        pdf_native=False,
        vision=False,
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        pricing_ref="glm-5",
        enabled=False,
        verified=False,
        notes="(verify) VL-only modality + SO reliability before enabling image tasks.",
    ),
    # Kimi K2.x — vision (verify); SO (verify).
    ModelCapability(
        model_id="openai_compatible/kimi-k2",
        display_name="Kimi K2 (Moonshot)",
        provider=Provider.openai_compatible,
        modalities=_TEXT,
        pdf_native=False,
        vision=False,
        structured_method=StructuredMethod.json_mode,
        needs_repair_fallback=True,
        pricing_ref="kimi-k2",
        enabled=False,
        verified=False,
        notes="(verify) vision + SO reliability.",
    ),
]


# id -> capability
registry: dict[str, ModelCapability] = {c.model_id: c for c in (_GEMINI + _STUBS)}


def get_capability(model_id: str) -> ModelCapability:
    """Return the capability profile for ``model_id`` or raise ``KeyError``."""
    try:
        return registry[model_id]
    except KeyError as exc:  # noqa: TRY003
        raise KeyError(
            f"Model '{model_id}' is not in the registry. "
            f"Add it to docs/models-and-caveats.md and registry.py first."
        ) from exc


def is_registered(model_id: str) -> bool:
    return model_id in registry


def list_models(*, enabled_only: bool = False) -> list[ModelCapability]:
    caps = list(registry.values())
    if enabled_only:
        caps = [c for c in caps if c.enabled]
    return caps

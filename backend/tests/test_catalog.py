"""Catalog integrity + availability-gating tests (offline)."""

from __future__ import annotations

from app.providers.capabilities import Modality
from app.providers.pricing import load_rate_card, resolve_pricing_ref
from app.providers.registry import (
    catalog_summary,
    families,
    gate_reason,
    list_models,
    registry,
)


def test_catalog_loads_many_families():
    summary = catalog_summary()
    # every required family is present
    for fam in ("gemini", "claude", "deepseek", "qwen", "kimi", "glm", "grok", "llama", "mistral"):
        assert fam in summary, fam
    assert len(registry) >= 70  # exhaustive, versioned catalog


def test_only_verified_callable_models_enabled_everything_else_gated_with_reason():
    enabled = {c.model_id for c in list_models(enabled_only=True)}
    assert enabled, "expected at least the Gemini family enabled"
    # Phase 2.5 live probe verified exactly these as callable on vertex-internal-testing:
    # Gemini 2.5 (flash/pro/flash-lite) + DeepSeek R1 + Qwen3-235B. Nothing unverified ships enabled.
    assert enabled == {
        "vertex_ai/gemini-2.5-flash",
        "vertex_ai/gemini-2.5-pro",
        "vertex_ai/gemini-2.5-flash-lite",
        "vertex_ai/deepseek-ai/deepseek-r1-0528-maas",
        "vertex_ai/qwen/qwen3-235b-a22b-instruct-2507-maas",
    }
    # Every gated-off model carries a non-empty reason.
    for cap in registry.values():
        if not cap.enabled:
            assert gate_reason(cap.model_id), cap.model_id


def test_thinking_and_non_thinking_are_first_class():
    # Grok 4.20 (Vertex) exposes BOTH reasoning and non-reasoning as separate configs.
    reasoning = registry["vertex_ai/xai/grok-4.20-reasoning"]
    non = registry["vertex_ai/xai/grok-4.20-non-reasoning"]
    assert reasoning.thinking is True
    assert non.thinking is False
    # Qwen3-next likewise.
    assert registry["vertex_ai/qwen/qwen3-next-80b-a3b-thinking-maas"].thinking is True
    assert registry["vertex_ai/qwen/qwen3-next-80b-a3b-instruct-maas"].thinking is False


def test_deepseek_r1_is_text_only_gate_target():
    cap = registry["vertex_ai/deepseek-ai/deepseek-r1-0528-maas"]
    assert cap.modalities == frozenset({Modality.text})
    assert cap.can_handle_documents() is False


def test_grok_vision_caveats_encoded():
    cap = registry["vertex_ai/xai/grok-4.20-reasoning"]
    assert cap.vision is True and cap.pdf_native is False
    assert cap.max_image_mb == 4.0
    assert cap.max_image_megapixels == 33.0
    assert cap.image_formats == frozenset({"jpeg", "png"})


def test_every_pricing_ref_resolves():
    card = load_rate_card()
    for cap in registry.values():
        if cap.pricing_ref:
            assert resolve_pricing_ref(cap.pricing_ref, card) is not None, cap.model_id


def test_families_grouping_covers_all_models():
    total = sum(len(v) for v in families().values())
    assert total == len(registry)

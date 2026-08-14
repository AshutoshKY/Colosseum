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
    for fam in (
        "gemini",
        "claude",
        "deepseek",
        "qwen",
        "kimi",
        "glm",
        "grok",
        "llama",
        "mistral",
        "bedrock",
    ):
        assert fam in summary, fam
    assert len(registry) >= 70  # exhaustive, versioned catalog


def test_only_verified_callable_models_enabled_everything_else_gated_with_reason():
    enabled = {c.model_id for c in list_models(enabled_only=True)}
    assert enabled, "expected at least the Gemini family enabled"
    # Phase 2.5 live probe verified exactly these as callable on vertex-internal-testing:
    # Gemini 2.5 (flash/pro/flash-lite) + DeepSeek R1 + Qwen3-235B. Nothing unverified ships enabled.
    assert enabled >= {
        "vertex_ai/gemini-2.5-flash",
        "vertex_ai/gemini-2.5-pro",
        "vertex_ai/gemini-2.5-flash-lite",
        "vertex_ai/deepseek-ai/deepseek-r1-0528-maas",
        "vertex_ai/qwen/qwen3-235b-a22b-instruct-2507-maas",
    }
    assert not {cap.model_id for cap in registry.values() if cap.enabled and not cap.verified}
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


def test_openrouter_claude_sonnet_4_accepts_document_input():
    cap = registry["openrouter/anthropic/claude-sonnet-4"]
    assert cap.pdf_native is True and cap.vision is True
    assert cap.modalities >= frozenset({Modality.text, Modality.image, Modality.pdf})


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


def test_openrouter_model_release_date():
    from decimal import Decimal

    from app.providers.openrouter import OpenRouterModel

    m = OpenRouterModel(
        id="openai/gpt-4o",
        name="GPT-4o",
        context_length=128000,
        input_usd_per_million=Decimal("2.5"),
        output_usd_per_million=Decimal("10.0"),
        modalities=("text", "image"),
        created=1715644800,
    )
    assert m.release_date == "2024-05-14"


def test_discover_vertex_models_endpoint():
    from app.api.routers.catalog import discover_vertex_models, get_vertex_status

    status = get_vertex_status()
    assert "has_credentials" in status

    discovery = discover_vertex_models()
    assert discovery.total >= 20
    assert any(m.model_id == "vertex_ai/gemini-2.0-flash" for m in discovery.discovered)
    assert any(m.model_id == "vertex_ai/claude-3-7-sonnet@20250219" for m in discovery.discovered)
    assert any(m.model_id == "vertex_ai/meta/llama-3.3-70b-instruct-maas" for m in discovery.discovered)


async def test_add_custom_model_and_delete():
    from app.api.routers.catalog import add_model_to_catalog, delete_model_from_catalog
    from app.api.schemas import AddModelIn
    from app.providers.registry import is_registered

    test_id = "vertex_ai/custom-test-gemini-model"
    payload = AddModelIn(
        model_id=test_id,
        display_name="Custom Gemini Test Model",
        provider="vertex_ai",
        family="gemini",
        pdf_native=True,
        vision=True,
        context_window=1000000,
        input_per_million=0.5,
        output_per_million=2.0,
        enabled=True,
        verify_now=False,
    )

    created = await add_model_to_catalog(payload)
    assert created.id == test_id
    assert is_registered(test_id)
    assert created.capabilities["pdf_native"] is True

    # Now delete
    res = delete_model_from_catalog(test_id)
    assert res["deleted"] is True
    assert not is_registered(test_id)


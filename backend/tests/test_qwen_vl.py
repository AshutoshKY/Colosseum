"""Qwen3-VL self-deployed catalog and endpoint plumbing tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.providers.adapters import DocumentInput, RasterizingAdapter, get_adapter
from app.providers.capabilities import Provider, StructuredMethod
from app.providers.gateway import ModelGateway
from app.providers.registry import get_capability, list_models


def test_qwen_vl_catalog_and_document_adapter():
    cap = get_capability("qwen3-vl-8b")
    assert cap.transport_model == "openai/Qwen/Qwen3-VL-8B-Instruct"
    assert cap.provider is Provider.openai_compatible
    assert cap.vision and not cap.pdf_native
    assert cap.structured_method is StructuredMethod.json_mode
    assert cap.needs_repair_fallback
    assert isinstance(get_adapter(cap), RasterizingAdapter)
    assert cap in list_models(enabled_only=True)


def test_qwen_vl_uses_its_per_model_endpoint_env(monkeypatch):
    monkeypatch.setenv("QWEN_VL_BASE_URL", "http://qwen.test/v1")
    monkeypatch.setenv("QWEN_VL_API_KEY", "test-key")
    kwargs = ModelGateway(trace=False)._provider_kwargs(get_capability("qwen3-vl-8b"), {})
    assert kwargs["api_base"] == "http://qwen.test/v1"
    assert kwargs["api_key"] == "test-key"


def test_gemini_31_thinking_level_maps_to_litellm_reasoning_effort():
    cap = get_capability("gemini-3.1-pro")
    assert cap.transport_model == "vertex_ai/gemini-3.1-pro-preview"
    assert cap.thinking == "level"
    kwargs = ModelGateway(trace=False)._provider_kwargs(cap, {"thinking_level": "low"})
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["vertex_location"] == "global"
    assert kwargs["temperature"] == 1.0
    assert "thinking" not in kwargs


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_qwen_vl_segregation_through_gateway():
    from app.tasks.schemas.opd_healthpay import DocumentSegregatorResponse

    pdf = Path(__file__).resolve().parents[2] / "test-docs" / "REQ65CYP9E0_1.pdf"
    if not pdf.is_file():
        pytest.skip(f"sample PDF missing: {pdf}")
    # QWEN_VL_* have safe vLLM defaults; explicit env values override them.
    result = await ModelGateway(trace=False).structured(
        model_id="qwen3-vl-8b",
        system="Classify the supplied claim document pages.",
        instruction="Return document segments with document_type and page ranges.",
        schema=DocumentSegregatorResponse,
        documents=[DocumentInput(path=str(pdf), page_ranges="1")],
        config={"max_output_tokens": 256},
    )
    assert result.valid, result.error

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


def test_claude_37_sonnet_on_vertex_capabilities():
    cap = get_capability("vertex_ai/claude-3-7-sonnet@20250219")
    assert cap.thinking is True
    assert cap.vision is True
    assert cap.pdf_native is True


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

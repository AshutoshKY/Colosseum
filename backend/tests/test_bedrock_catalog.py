"""Bedrock catalog and gateway plumbing tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.providers import DocumentInput
from app.providers.capabilities import Provider, StructuredMethod
from app.providers.gateway import ModelGateway, ProviderAuthError
from app.providers.registry import get_capability, list_models
from pydantic import BaseModel


def test_bedrock_catalog_entries_are_gated_until_live_verification():
    caps = list_models(provider=Provider.bedrock)
    assert {cap.model_id for cap in caps} >= {
        "bedrock-claude-sonnet-4-5",
        "bedrock-nova-pro",
        "bedrock-nova-lite",
        "bedrock-nova-micro",
    }
    assert all(not cap.enabled and not cap.verified for cap in caps)
    claude = get_capability("bedrock-claude-sonnet-4-5")
    assert claude.transport_model.startswith("bedrock/")
    assert claude.provider is Provider.bedrock
    assert claude.vision and not claude.pdf_native
    assert claude.structured_method is StructuredMethod.tools


def test_bedrock_kwargs_require_token_and_include_region(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    gateway = ModelGateway(trace=False)
    gateway.settings.aws_bearer_token_bedrock = None
    cap = get_capability("bedrock-nova-pro")

    with pytest.raises(ProviderAuthError, match="token missing"):
        gateway._provider_kwargs(cap, {})

    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-token")
    kwargs = gateway._provider_kwargs(cap, {})
    assert kwargs["aws_region_name"] == "ap-south-1"
    assert kwargs["api_key"] == "test-token"


def test_expired_bedrock_token_gets_clear_error():
    cap = get_capability("bedrock-nova-pro")

    class Expired(Exception):
        status_code = 403

    with pytest.raises(ProviderAuthError, match="token expired"):
        ModelGateway._raise_provider_auth_error(
            cap, Expired("ExpiredTokenException: token has expired")
        )


class _Ok(BaseModel):
    ok: bool


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bedrock_pdf_through_gateway():
    if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        pytest.skip("AWS_BEARER_TOKEN_BEDROCK is not configured")
    pdf = Path(__file__).resolve().parents[2] / "test-docs" / "REQ65CYP9E0_1.pdf"
    if not pdf.is_file():
        pytest.skip(f"sample PDF missing: {pdf}")
    result = await ModelGateway(trace=False).structured(
        model_id="bedrock-nova-lite",
        system="Return JSON only.",
        instruction='Inspect the document and return {"ok": true}.',
        schema=_Ok,
        documents=[DocumentInput(path=str(pdf), page_ranges="1")],
        config={"max_output_tokens": 32},
    )
    assert result.valid, result.error

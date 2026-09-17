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


def test_bedrock_catalog_entries_are_live_verified():
    # The catalog contains Bedrock models for us-east-1: every entry is callable
    # with valid credentials / token, and all ship enabled + verified.
    caps = list_models(provider=Provider.bedrock)
    assert {cap.model_id for cap in caps} >= {
        "bedrock-qwen3-vl-235b",
        "bedrock-nova-pro",
        "bedrock-nova-lite",
        "bedrock-nova-micro",
        "bedrock-glm-4-7-flash",
    }
    assert all(cap.enabled and cap.verified for cap in caps)
    # Every transport id is a bedrock/ route; profile-gated models carry a us./global. prefix.
    assert all(cap.transport_model.startswith("bedrock/") for cap in caps)

    # GLM 4.7 Flash
    glm_flash = get_capability("bedrock-glm-4-7-flash")
    assert glm_flash.transport_model == "bedrock/zai.glm-4.7-flash"
    assert glm_flash.provider is Provider.bedrock
    assert glm_flash.thinking in (True, "budget")

    # Qwen3-VL — vision model; correct id has no -instruct suffix.
    qwen_vl = get_capability("bedrock-qwen3-vl-235b")
    assert qwen_vl.transport_model == "bedrock/qwen.qwen3-vl-235b-a22b"
    assert qwen_vl.provider is Provider.bedrock
    assert qwen_vl.vision and not qwen_vl.pdf_native

    claude = get_capability("bedrock-claude-opus-4-5")
    assert claude.transport_model == "bedrock/global.anthropic.claude-opus-4-5-20251101-v1:0"
    assert claude.vision and not claude.pdf_native
    assert claude.structured_method is StructuredMethod.tools

    # Nova on-demand in us-east-1 goes through the us. cross-region inference profile.
    assert get_capability("bedrock-nova-pro").transport_model.startswith("bedrock/us.")


def test_bedrock_kwargs_require_credentials_and_include_region(monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    gateway = ModelGateway(trace=False)
    gateway.settings.aws_bearer_token_bedrock = None
    gateway.settings.aws_access_key_id = None
    gateway.settings.aws_secret_access_key = None
    cap = get_capability("bedrock-nova-pro")

    with pytest.raises(ProviderAuthError, match="credentials missing"):
        gateway._provider_kwargs(cap, {})

    # IAM credentials path (SigV4 auto-renewal)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    kwargs = gateway._provider_kwargs(cap, {})
    assert kwargs["aws_region_name"] == gateway.settings.aws_region_name
    assert kwargs["aws_access_key_id"] == "test-key-id"
    assert kwargs["aws_secret_access_key"] == "test-secret-key"
    assert "api_key" not in kwargs

    # Bearer token fallback path
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-token")
    kwargs_token = gateway._provider_kwargs(cap, {})
    assert kwargs_token["aws_region_name"] == gateway.settings.aws_region_name
    assert kwargs_token["api_key"] == "test-token"


def test_expired_bedrock_token_gets_clear_error():
    cap = get_capability("bedrock-nova-pro")

    class Expired(Exception):
        status_code = 403

    with pytest.raises(ProviderAuthError, match="token expired"):
        ModelGateway._raise_provider_auth_error(
            cap, Expired("ExpiredTokenException: token has expired")
        )


def test_gateway_region_override(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    gateway = ModelGateway(region="us-west-2", trace=False)
    cap = get_capability("bedrock-nova-pro")
    kwargs = gateway._provider_kwargs(cap, {})
    assert kwargs["aws_region_name"] == "us-west-2"


@pytest.mark.asyncio
async def test_catalog_regions_and_search():
    import httpx
    from app.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Test GET /api/catalog/regions
        res = await client.get("/api/catalog/regions")
        assert res.status_code == 200
        data = res.json()
        assert "bedrock" in data
        assert "vertex_ai" in data
        assert any(r["id"] == "us-east-1" for r in data["bedrock"])
        assert any(r["id"] == "us-west-2" for r in data["bedrock"])
        assert any(r["id"] == "ap-south-1" for r in data["bedrock"])

        # Test POST /api/catalog/providers/bedrock/region
        set_res = await client.post("/api/catalog/providers/bedrock/region", json={"region": "us-west-2"})
        assert set_res.status_code == 200
        assert set_res.json()["region"] == "us-west-2"

        # Reset back to us-east-1
        await client.post("/api/catalog/providers/bedrock/region", json={"region": "us-east-1"})

        # Test POST /api/catalog/discover/bedrock with region param
        disc = await client.post("/api/catalog/discover/bedrock?region=us-west-2")
        assert disc.status_code == 200
        disc_data = disc.json()
        assert disc_data["region"] == "us-west-2"
        assert "available_regions" in disc_data
        assert len(disc_data["discovered"]) > 0

        # Test GET /api/catalog/search with region filter
        search_reg = await client.get("/api/catalog/search?region=us-east-1")
        assert search_reg.status_code == 200
        assert search_reg.json()["total"] > 0

        # Test GET /api/catalog/search with text query matching region or name
        search_q = await client.get("/api/catalog/search?q=qwen")
        assert search_q.status_code == 200
        assert any("qwen" in m["id"].lower() for m in search_q.json()["models"])

        # Test multi-keyword search for GLM 4.7 Flash
        search_glm = await client.get("/api/catalog/search?q=4.7+flash+glm")
        assert search_glm.status_code == 200
        assert any("glm-4-7-flash" in m["id"].lower() for m in search_glm.json()["models"])


class _Ok(BaseModel):
    ok: bool


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bedrock_pdf_through_gateway():
    gateway = ModelGateway(trace=False)
    if not gateway.settings.has_bedrock_credentials:
        pytest.skip("Bedrock credentials are not configured")
    pdf = Path(__file__).resolve().parents[2] / "test-docs" / "REQ65CYP9E0_1.pdf"
    if not pdf.is_file():
        pytest.skip(f"sample PDF missing: {pdf}")
    result = await gateway.structured(
        model_id="bedrock-qwen3-vl-235b",
        system="Return JSON only.",
        instruction='Inspect the document and return {"ok": true}.',
        schema=_Ok,
        documents=[DocumentInput(path=str(pdf), page_ranges="1")],
        config={"max_output_tokens": 32},
    )
    assert result.valid, result.error

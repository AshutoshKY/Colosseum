"""Capability-gate unit tests: a text-only model is gated out of image/PDF tasks."""

from __future__ import annotations

import pytest
from app.providers.adapters import CapabilityGateError, DocumentInput
from app.providers.adapters.base import ProviderAdapter
from app.providers.capabilities import (
    Access,
    Modality,
    ModelCapability,
    Provider,
    StructuredMethod,
)
from app.providers.registry import get_capability


def _text_only_cap() -> ModelCapability:
    return ModelCapability(
        model_id="vertex_ai/deepseek-r1",
        display_name="DeepSeek R1",
        provider=Provider.vertex_partner,
        access=Access.maas,
        modalities=frozenset({Modality.text}),
        pdf_native=False,
        vision=False,
        structured_method=StructuredMethod.json_mode,
    )


def test_text_only_model_gated_out_of_pdf_task():
    adapter = ProviderAdapter(_text_only_cap())
    with pytest.raises(CapabilityGateError) as exc:
        adapter.gate([DocumentInput(path="/tmp/x.pdf")])
    assert "text-only" in str(exc.value).lower()


def test_registry_deepseek_is_text_only_and_cannot_handle_documents():
    # R1 is verified callable (Phase 2.5 live probe) but still TEXT-ONLY: the gate must skip it
    # on document tasks (recorded "not applicable", never failed).
    cap = get_capability("vertex_ai/deepseek-ai/deepseek-r1-0528-maas")
    assert cap.vision is False
    assert cap.pdf_native is False
    assert cap.can_handle_documents() is False
    assert cap.enabled is True  # verified callable on vertex-internal-testing
    # An un-probed DeepSeek variant stays gated off until verified.
    assert get_capability("vertex_ai/deepseek-ai/deepseek-v3.1-maas").enabled is False


def test_gemini_passes_pdf_gate():
    cap = get_capability("vertex_ai/gemini-2.5-flash")
    adapter = ProviderAdapter(cap)
    # should not raise
    adapter.gate([DocumentInput(path="/tmp/x.pdf")])
    assert cap.pdf_native is True
    assert cap.enabled is True
    assert cap.verified is True


def test_vision_model_with_no_pdf_native_still_passes_gate():
    # Grok: not pdf_native but vision -> can take rasterized images, so gate allows it.
    cap = get_capability("xai/grok-4-0709")
    adapter = ProviderAdapter(cap)
    adapter.gate([DocumentInput(path="/tmp/x.pdf")])
    assert cap.vision is True
    assert cap.pdf_native is False
    assert cap.max_image_mb == 4.0  # the 4 MB caveat is encoded

"""``ModelCapability`` — the per-model capability profile.

This mirrors the field set in ``docs/models-and-caveats.md`` ("Capability profile").
The registry (``registry.py``) is generated to match the seed caveats table there and the
two must never drift. Every caveat the gateway/adapter layer enforces (PDF-native pass-through
vs rasterization, image size/format/resolution caps, payload caps, structured-output method,
thinking/cache) is encoded here so callers never special-case a model.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Provider(str, Enum):
    vertex_ai = "vertex_ai"
    vertex_partner = "vertex_partner"
    xai = "xai"
    openai_compatible = "openai_compatible"
    openrouter = "openrouter"
    bedrock = "bedrock"


class Access(str, Enum):
    maas = "maas"  # managed / serverless
    self_deploy = "self_deploy"  # GPU/TPU endpoint (cold-start 429, VM-uptime billing)


class Modality(str, Enum):
    text = "text"
    image = "image"
    pdf = "pdf"
    audio = "audio"
    video = "video"


class StructuredMethod(str, Enum):
    json_schema = "json_schema"
    json_mode = "json_mode"
    tools = "tools"


class ModelCapability(BaseModel):
    """Immutable capability profile for one registered model.

    Field semantics match ``docs/models-and-caveats.md``. ``(verify)`` cells from the seed
    table are encoded conservatively (disabled / ``verified=False``) until confirmed live.
    """

    model_config = {"frozen": True}

    model_id: str = Field(description="Stable Colosseum catalog id.")
    litellm_model: str | None = Field(
        default=None,
        description="LiteLLM transport id when it differs from the catalog id.",
    )
    display_name: str
    provider: Provider
    access: Access = Access.maas

    # --- modalities / document handling ---
    modalities: frozenset[Modality] = Field(default_factory=lambda: frozenset({Modality.text}))
    pdf_native: bool = Field(
        default=False,
        description="True: model ingests PDF directly. False: adapter rasterizes to images.",
    )
    vision: bool = Field(default=False, description="Accepts image input.")

    # --- size / format caps (the caveats the adapter enforces) ---
    max_image_mb: float | None = Field(
        default=None, description="Per-image base64 cap in MB (e.g. Grok 4 MB)."
    )
    max_payload_mb: float | None = Field(
        default=None, description="Total request payload cap in MB (e.g. Vertex 30 MB)."
    )
    max_image_megapixels: float | None = Field(
        default=None, description="Per-image resolution cap (e.g. Grok ~33 MP)."
    )
    image_formats: frozenset[str] = Field(
        default_factory=lambda: frozenset({"png", "jpeg"}),
        description="Accepted raster formats for image input.",
    )

    context_window: int | None = Field(default=None, description="Input token budget.")

    # --- structured output ---
    structured_method: StructuredMethod = StructuredMethod.json_schema
    needs_repair_fallback: bool = Field(
        default=False,
        description="Weak structured-output models need the free-text->JSON repair ladder.",
    )

    # --- billing-relevant extras ---
    thinking: bool | Literal["budget", "level"] = Field(
        default=False,
        description="Reasoning support: false, budget tokens, or Gemini-style levels.",
    )
    caching: bool = Field(default=False, description="Prompt/context caching supported.")
    batch: bool = Field(default=False, description="Batch API available.")

    pricing_ref: str | None = Field(
        default=None, description="Key into the rate card (input/output/cache/thinking $/1M)."
    )
    enabled: bool = Field(
        default=False,
        description="Whether Colosseum runs this model. Unverified providers ship disabled.",
    )
    verified: bool = Field(
        default=False,
        description="Capability flags confirmed live against provider docs (not assumed).",
    )
    release_date: str | None = Field(
        default=None,
        description="Release / launch date of the model (e.g. '2024-05-14').",
    )
    notes: str | None = None

    # Optional per-model environment indirection for OpenAI-compatible endpoints and regions.
    base_url_env: str | None = None
    api_key_env: str | None = None
    vertex_location: str | None = None
    default_region: str | None = Field(
        default=None,
        description="Default cloud region (e.g. us-east-1, us-central1, global).",
    )
    regions: frozenset[str] = Field(
        default_factory=frozenset,
        description="Supported cloud regions for this model (e.g. us-east-1, us-west-2, ap-south-1).",
    )

    # ------------------------------------------------------------------ helpers
    def supports_modality(self, modality: Modality) -> bool:
        return modality in self.modalities

    def can_handle_documents(self) -> bool:
        """Whether this model can take document input at all (PDF native or via images)."""
        return self.pdf_native or self.vision

    @property
    def transport_model(self) -> str:
        """Model identifier passed to LiteLLM."""
        return self.litellm_model or self.model_id

    def to_json(self) -> dict[str, object]:
        """JSON-able dict for persisting onto ``model_catalog.capabilities``."""
        data = self.model_dump(mode="json")
        data["modalities"] = sorted(m.value for m in self.modalities)
        data["image_formats"] = sorted(self.image_formats)
        data["regions"] = sorted(self.regions)
        return data

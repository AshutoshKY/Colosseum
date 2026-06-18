"""``model_catalog`` — registered models and their capability profile."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models._base import JSONB_VARIANT, created_at_field


class ModelCatalog(SQLModel, table=True):
    __tablename__ = "model_catalog"

    id: int | None = Field(default=None, primary_key=True)
    model_id: str = Field(index=True, unique=True, description="LiteLLM model id, e.g. vertex_ai/gemini-2.5-flash")
    provider: str = Field(index=True, description="vertex_ai | vertex_partner | xai | openai_compatible")
    display_name: str
    access: str = Field(default="maas", description="maas | self_deploy")
    capabilities: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB_VARIANT))
    pricing_ref: str | None = Field(default=None, index=True)
    enabled: bool = Field(default=True, index=True)
    notes: str | None = None
    created_at: Any = created_at_field()

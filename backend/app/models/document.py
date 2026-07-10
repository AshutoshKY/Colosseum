"""``document_sample`` — a sample claim document under test."""

from __future__ import annotations

from typing import Any

from sqlmodel import Field, SQLModel

from app.models._base import created_at_field


class DocumentSample(SQLModel, table=True):
    __tablename__ = "document_sample"

    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(index=True, description="Absolute or repo-relative path to the file")
    claim_type: str | None = Field(default=None, index=True)
    page_count: int | None = None
    sha256: str = Field(index=True, unique=True)
    origin: str = Field(default="test-docs", index=True)
    created_at: Any = created_at_field()

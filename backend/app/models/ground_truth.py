"""``ground_truth`` — optional labeled gold JSON per (document, task) for field metrics."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models._base import JSONB_VARIANT, created_at_field


class GroundTruth(SQLModel, table=True):
    __tablename__ = "ground_truth"
    __table_args__ = (UniqueConstraint("document_id", "task", name="uq_ground_truth_doc_task"),)

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document_sample.id", index=True)
    task: str = Field(index=True)
    gold: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB_VARIANT))
    created_at: Any = created_at_field()

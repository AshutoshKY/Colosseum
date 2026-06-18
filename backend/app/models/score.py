"""``score`` — multi-signal scoring attached to a run result (Phase 3 populates it)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Numeric
from sqlmodel import Field, SQLModel

from app.models._base import JSONB_VARIANT, created_at_field


class Score(SQLModel, table=True):
    __tablename__ = "score"

    id: int | None = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="run_result.id", index=True)
    field_metrics: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB_VARIANT))
    judge_score: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB_VARIANT))
    composite: float | None = Field(default=None, sa_column=Column(Numeric(10, 6)))
    rank: int | None = Field(default=None, index=True)
    created_at: Any = created_at_field()

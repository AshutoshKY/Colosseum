"""Persisted LLM-judge comparisons."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Numeric
from sqlmodel import Field, SQLModel

from app.models._base import JSONB_VARIANT, created_at_field


class JudgeComparison(SQLModel, table=True):
    __tablename__ = "judgecomparison"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="benchmark_run.id", index=True)
    task_name: str = Field(index=True)
    document_id: int = Field(foreign_key="document_sample.id", index=True)
    mode: str = Field(index=True)
    judge_model: str = Field(index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB_VARIANT))
    rationale: str | None = None
    cost_usd: float | None = Field(default=None, sa_column=Column(Numeric(14, 8)))
    created_at: Any = created_at_field()

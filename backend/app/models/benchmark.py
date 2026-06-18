"""Benchmark run tables: ``benchmark_run`` -> ``run_cell`` -> ``run_result``.

``run_result`` extends superclaims-ai's ``LLMCallLog`` with thinking/cached token
classes, a parsed structured output, multi-class cost breakdown, and latency.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy import Column, Numeric
from sqlmodel import Field, SQLModel

from app.models._base import JSONB_VARIANT, created_at_field


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"  # e.g. capability-gated (text-only model on an image task)


class BenchmarkRun(SQLModel, table=True):
    __tablename__ = "benchmark_run"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    task_pack_version: str = Field(default="v1")
    status: RunStatus = Field(default=RunStatus.pending, index=True)
    created_at: Any = created_at_field()


class RunCell(SQLModel, table=True):
    """One (task x document x model x config) coordinate of the run matrix."""

    __tablename__ = "run_cell"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="benchmark_run.id", index=True)
    task: str = Field(index=True)
    document_id: int = Field(foreign_key="document_sample.id", index=True)
    model_id: str = Field(index=True)
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB_VARIANT))
    status: RunStatus = Field(default=RunStatus.pending, index=True)
    skip_reason: str | None = None
    created_at: Any = created_at_field()


class RunResult(SQLModel, table=True):
    """The full record of a single model call. Extends LLMCallLog."""

    __tablename__ = "run_result"

    id: int | None = Field(default=None, primary_key=True)
    cell_id: int = Field(foreign_key="run_cell.id", index=True)

    # --- output ---
    raw_response: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB_VARIANT))
    parsed_output: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB_VARIANT))
    valid: bool = Field(default=False, index=True)

    # --- token classes (canonical, normalized across providers) ---
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0

    # --- cost (USD) ---
    est_input_cost: float | None = Field(default=None, sa_column=Column(Numeric(14, 8)))
    est_output_cost: float | None = Field(default=None, sa_column=Column(Numeric(14, 8)))
    est_cache_cost: float | None = Field(default=None, sa_column=Column(Numeric(14, 8)))
    est_thinking_cost: float | None = Field(default=None, sa_column=Column(Numeric(14, 8)))
    total_cost_usd: float | None = Field(default=None, sa_column=Column(Numeric(14, 8)))
    pricing_version: str | None = None

    # --- performance / reliability ---
    latency_ms: int | None = None
    retries: int = 0
    error: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB_VARIANT))

    # --- provenance ---
    usage_raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB_VARIANT))
    structured_method: str | None = None
    endpoint: str | None = Field(default=None, description="region/global endpoint for fair cost compare")

    created_at: Any = created_at_field()

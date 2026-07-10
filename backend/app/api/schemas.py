"""Request and response schemas used by the React client and OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CountsOut(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0


class RunCreated(BaseModel):
    run_id: int
    status: str


class RunPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RunOut(BaseModel):
    run_id: int
    name: str
    pack: str
    status: str
    created_at: datetime
    counts: CountsOut
    spec: dict[str, Any]
    cost_usd: float = 0.0
    judge_status: str | None = None


class CellOut(BaseModel):
    document_id: int
    document_name: str
    model_id: str
    task: str
    status: str
    latency_ms: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    skip_reason: str | None = None


class RunDetailOut(BaseModel):
    run: RunOut
    cells: list[CellOut]


class CostEstimateOut(BaseModel):
    total_usd: float
    estimated: Literal[True] = True
    assumed_input_tokens_per_cell: int
    assumed_output_tokens_per_cell: int
    priced_cells: int


class DryRunOut(BaseModel):
    layers: list[list[str]]
    gold_requirements: dict[str, list[str]]
    cost_estimate: CostEstimateOut


class ResultOut(CellOut):
    result_id: int | None = None
    parsed_output: dict[str, Any] | None = None
    prompt_system: str | None = None
    prompt_instruction: str | None = None
    raw_response: Any | None = None
    valid: bool | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    retries: int = 0
    score: dict[str, Any] | None = None


class ResultsOut(BaseModel):
    results: list[ResultOut]


class JudgeRequest(BaseModel):
    model_id: str | None = None
    modes: list[Literal["gold_grade", "doc_grade", "head_to_head"]]


class JudgeJobOut(BaseModel):
    run_id: int
    status: str


class DocumentOut(BaseModel):
    id: int
    filename: str
    sha256: str
    page_count: int | None = None
    origin: str
    has_gold: bool
    gold_keys: list[str] = Field(default_factory=list)
    gold_summary: dict[str, bool] = Field(default_factory=dict)


class GoldBody(BaseModel):
    tasks: dict[str, Any]


class GoldOut(GoldBody):
    document_id: int


class PromptVersionIn(BaseModel):
    system_prompt: str
    instruction_template: str
    activate: bool = True
    source_repo: str | None = None
    source_branch: str | None = None
    source_path: str | None = None


class PromptVersionOut(BaseModel):
    id: int | None = None
    pack: str
    task_name: str
    version: int | None = None
    system_prompt: str
    instruction_template: str
    source_repo: str | None = None
    source_branch: str | None = None
    source_path: str | None = None
    active: bool
    created_at: datetime | None = None
    active_version: int | None = None
    differs_from_code: bool = False
    source: str | None = None


class PromptPreviewIn(BaseModel):
    pack: str
    task: str
    system_prompt: str | None = None
    instruction_template: str | None = None
    sample_document_id: int | None = None


class PromptPreviewOut(BaseModel):
    pack: str
    task: str
    system_prompt: str
    instruction_template: str
    rendered_instruction: str
    unresolved_variables: list[str] = Field(default_factory=list)


class ReferenceRuntimeOut(BaseModel):
    model_id: str | None = None
    thinking_budget: int | None = None
    thinking_level: str | None = None
    max_output_tokens: int | None = None
    timeout_s: float | None = None


class TaskOut(BaseModel):
    name: str
    deterministic: bool
    depends_on: list[str]
    document_types: list[str]
    is_text_task: bool
    reference_runtime: ReferenceRuntimeOut
    gold_feed_keys: list[str]


class PackOut(BaseModel):
    name: str
    variants: list[str] = Field(default_factory=list)
    order: list[str]
    dependency_graph: dict[str, list[str]]
    tasks: list[TaskOut]
    variant_tasks: dict[str, list[TaskOut]] = Field(default_factory=dict)
    error: str | None = None


class CatalogModelOut(BaseModel):
    id: str
    model_id: str
    name: str
    provider: str
    family: str
    enabled: bool
    verified: bool
    gate_reason: str | None = None
    capabilities: dict[str, Any]
    pricing: dict[str, float | None]


class CatalogOut(BaseModel):
    models: list[CatalogModelOut]
    providers: dict[str, list[CatalogModelOut]]
    summary: dict[str, dict[str, int]]


class VerifyOut(BaseModel):
    ok: bool
    error: str | None = None
    latency_ms: int
    yaml_snippet: str | None = None


class LeaderboardRow(BaseModel):
    task: str
    model: str
    model_id: str
    cells: int
    valid_percent: float
    accuracy: float | None = None
    cost_usd: float
    cost_per_doc: float
    median_latency_ms: int | None = None
    composite: float
    rank: int | None = None
    judge_score: float | None = None
    mean_rank: float | None = None
    win_rate: float | None = None
    judged_cells: int | None = None


class FieldRow(BaseModel):
    path: str
    per_model: dict[str, float]


class FieldBreakdownOut(BaseModel):
    task: str
    fields: list[FieldRow]


class SideBySideOut(BaseModel):
    document_id: int
    task: str
    gold: Any | None = None
    models: dict[str, dict[str, Any]]
    outputs: list[dict[str, Any]]
    judge: list[dict[str, Any]]

"""Validated, serializable configuration for one benchmark run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, select

from app.models import DocumentSample, GroundTruth
from app.providers.registry import get_capability
from app.tasks.base import TaskPack
from app.tasks.claim_types import get_task_pack


class PromptOverride(BaseModel):
    system_prompt: str | None = None
    instruction_template: str | None = None


class RuntimeOverride(BaseModel):
    model_id: str | None = None
    thinking_budget: int | None = None
    thinking_level: Literal["minimal", "low", "medium"] | None = None
    max_output_tokens: int | None = None
    timeout_s: float | None = Field(default=None, gt=0)


class CompressionSpec(BaseModel):
    """Optional aggressive image compression so rasterized pages fit a model's context window.

    When ``enabled``, the rasterizing adapter caps each page at ``max_megapixels`` (in addition
    to any per-model catalog cap, taking the smaller of the two) before size compression. This
    keeps the vision-token count under the model's ``context_window`` — e.g. self-deployed
    Qwen3-VL-8B (max_model_len 26032), where a full-resolution scanned page alone can exceed the
    whole window and make the endpoint hang.
    """

    enabled: bool = False
    max_megapixels: float = Field(default=4.0, gt=0)
    max_image_mb: float | None = Field(default=None, gt=0)


class ConcurrencySpec(BaseModel):
    global_: int = Field(default=16, alias="global", ge=1)
    per_provider: dict[str, int] = Field(
        default_factory=lambda: {
            "vertex_ai": 4,
            "vertex_partner": 4,
            "openai_compatible": 8,
            "openrouter": 8,
            "bedrock": 4,
            "xai": 2,
        }
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_provider_limits(self) -> ConcurrencySpec:
        invalid = {name: value for name, value in self.per_provider.items() if value < 1}
        if invalid:
            raise ValueError(f"Provider concurrency values must be >= 1: {invalid}")
        return self


class JudgeSpec(BaseModel):
    enabled: bool = False
    model_id: str = "gemini-3.1-pro"
    modes: list[Literal["gold_grade", "doc_grade", "head_to_head"]] = Field(
        default_factory=lambda: ["gold_grade", "head_to_head"]
    )


class RunSpec(BaseModel):
    name: str = Field(min_length=1)
    pack: Literal["OPD", "IPD"]
    variant: Literal["CL", "RM", "PP"] | None = None
    selected_tasks: list[str] = Field(min_length=1)
    document_ids: list[int] = Field(min_length=1)
    model_ids: list[str] = Field(min_length=1)
    upstream_mode: Literal["gold", "model"] = "gold"
    prompt_overrides: dict[str, PromptOverride] = Field(default_factory=dict)
    runtime_overrides: dict[str, RuntimeOverride] = Field(default_factory=dict)
    concurrency: ConcurrencySpec = Field(default_factory=ConcurrencySpec)
    judge: JudgeSpec = Field(default_factory=JudgeSpec)
    compression: CompressionSpec = Field(default_factory=CompressionSpec)
    confirm_large: bool = False

    @model_validator(mode="after")
    def validate_catalog_and_pack(self) -> RunSpec:
        pack = planning_pack(self)
        unknown = sorted(set(self.selected_tasks) - pack.tasks.keys())
        if unknown:
            raise ValueError(f"Unknown tasks for {self.pack}: {', '.join(unknown)}")
        pack.resolve_subset(self.selected_tasks, self.upstream_mode)

        disabled: list[str] = []
        for model_id in self.model_ids:
            try:
                capability = get_capability(model_id)
            except KeyError as e:
                raise ValueError(str(e)) from e
            if not capability.enabled:
                disabled.append(model_id)
        for task_name, override in self.runtime_overrides.items():
            if task_name not in pack.tasks:
                raise ValueError(f"Unknown runtime override task: {task_name}")
            if override.model_id:
                try:
                    capability = get_capability(override.model_id)
                except KeyError as e:
                    raise ValueError(str(e)) from e
                if not capability.enabled:
                    disabled.append(override.model_id)
        if disabled:
            raise ValueError(f"Models are not enabled: {', '.join(disabled)}")
        if self.judge.enabled:
            try:
                judge_capability = get_capability(self.judge.model_id)
            except KeyError as e:
                raise ValueError(str(e)) from e
            if not judge_capability.enabled or not judge_capability.verified:
                raise ValueError(f"Judge model must be enabled and verified: {self.judge.model_id}")
        cells = len(self.document_ids) * len(self.model_ids) * len(self.selected_tasks)
        if cells > 100 and not self.confirm_large:
            raise ValueError(f"Run has {cells} cells; set confirm_large=true to continue")
        return self

    def validate_documents(self, session: Session) -> list[int]:
        found = set(
            session.exec(
                select(DocumentSample.id).where(DocumentSample.id.in_(self.document_ids))  # type: ignore[union-attr]
            ).all()
        )
        return sorted(set(self.document_ids) - found)

    def validate_gold(self, session: Session) -> dict[int, list[str]]:
        """Return missing required gold keys keyed by document id."""
        plan = planning_pack(self).resolve_subset(self.selected_tasks, self.upstream_mode)
        required = {key for keys in plan.gold_requirements.values() for key in keys}
        if not required:
            return {}
        rows = session.exec(
            select(GroundTruth).where(GroundTruth.document_id.in_(self.document_ids))  # type: ignore[union-attr]
        ).all()
        by_doc: dict[int, set[str]] = {doc_id: set() for doc_id in self.document_ids}
        for row in rows:
            by_doc.setdefault(row.document_id, set()).add(row.task)
            tasks = row.gold.get("tasks") if isinstance(row.gold, dict) else None
            if isinstance(tasks, dict):
                by_doc[row.document_id].update(tasks)
        aliases = {"merge_bills": "upstream_bills", "benefits": "upstream_benefits"}
        report: dict[int, list[str]] = {}
        for doc_id, available in by_doc.items():
            missing = sorted(
                key
                for key in required
                if key not in available and aliases.get(key) not in available
            )
            if missing:
                report[doc_id] = missing
        return report


def task_pack_for(pack: str, variant: str | None = None) -> TaskPack:
    try:
        loaded = get_task_pack(pack, variant)  # type: ignore[call-arg]
    except TypeError:
        loaded = get_task_pack(variant or pack)
    if isinstance(loaded, TaskPack):
        return loaded
    if pack == "OPD":
        from app.tasks.opd import OPD_PIPE_ORDER

        order = OPD_PIPE_ORDER
    else:
        order = list(loaded)
    return TaskPack(name=pack, tasks=loaded, order=order)


def planning_pack(spec: RunSpec) -> TaskPack:
    """Use the temporary OPD dependency metadata until the task pack carries its own."""
    from app.runner.engine import execution_pack

    return execution_pack(spec)


def runtime_config(spec: RunSpec, task_name: str, task: Any) -> dict[str, Any]:
    """Merge a task's reference runtime with its per-run override."""
    values = {
        "thinking_budget": task.reference_runtime.thinking_budget,
        "thinking_level": task.reference_runtime.thinking_level,
        "max_output_tokens": task.reference_runtime.max_output_tokens,
        "timeout_s": task.reference_runtime.timeout_s,
    }
    override = spec.runtime_overrides.get(task_name)
    if override:
        values.update(override.model_dump(exclude_none=True))
    config = {key: value for key, value in values.items() if value is not None}
    if spec.compression.enabled:
        config["compression"] = spec.compression.model_dump()
    return config

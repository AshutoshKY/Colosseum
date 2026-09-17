"""Task-pack metadata for the run builder."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import PackOut, ReferenceRuntimeOut, TaskOut
from app.runner.engine import OPD_DEPENDS, OPD_GOLD_KEYS
from app.runner.spec import task_pack_for

router = APIRouter(prefix="/packs", tags=["packs"])


def _task_out(task, *, pack: str) -> TaskOut:
    depends_on = task.depends_on or (OPD_DEPENDS.get(task.name, ()) if pack == "OPD" else ())
    gold_keys = task.gold_feed_keys or (OPD_GOLD_KEYS.get(task.name, ()) if pack == "OPD" else ())
    runtime = task.reference_runtime
    return TaskOut(
        name=task.name,
        deterministic=task.deterministic,
        depends_on=list(depends_on),
        document_types=sorted(task.document_types),
        is_text_task=task.is_text_task,
        reference_runtime=ReferenceRuntimeOut(
            model_id=runtime.model_id,
            thinking_budget=runtime.thinking_budget,
            thinking_level=runtime.thinking_level,
            max_output_tokens=runtime.max_output_tokens,
            timeout_s=runtime.timeout_s,
        ),
        gold_feed_keys=list(gold_keys),
        gold_context_keys=list(task.gold_context_keys),
    )


def _load(pack: str, variant: str | None = None):
    try:
        return task_pack_for(pack, variant)
    except (KeyError, NotImplementedError, TypeError, ValueError):
        return None


def _pack_out(pack_name: str, variants: list[str]) -> PackOut:
    loaded_variants = {variant: _load(pack_name, variant) for variant in variants}
    default = _load(pack_name) or next((pack for pack in loaded_variants.values() if pack), None)
    if default is None:
        return PackOut(
            name=pack_name,
            variants=variants,
            order=[],
            dependency_graph={},
            tasks=[],
            error="Task pack is not installed yet",
        )
    tasks = [_task_out(default.tasks[name], pack=pack_name) for name in default.order]
    return PackOut(
        name=pack_name,
        variants=variants,
        order=list(default.order),
        dependency_graph={task.name: task.depends_on for task in tasks},
        tasks=tasks,
        variant_tasks={
            variant: [_task_out(value.tasks[name], pack=pack_name) for name in value.order]
            for variant, value in loaded_variants.items()
            if value is not None
        },
    )


@router.get("", response_model=list[PackOut])
def get_packs() -> list[PackOut]:
    return [_pack_out("OPD", []), _pack_out("IPD", ["CL", "RM", "PP"])]

"""Resolve prompts with per-run overrides taking highest precedence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.models import PromptVersion
from app.tasks.base import Task


@dataclass(frozen=True)
class ResolvedPrompt:
    system_prompt: str
    instruction_template: str
    source: str


def resolve_prompt(
    session: Session,
    pack: str,
    task: Task,
    overrides: dict[str, Any] | Any | None = None,
) -> ResolvedPrompt:
    override = (
        overrides.model_dump(exclude_none=True)
        if hasattr(overrides, "model_dump")
        else (overrides or {})
    )
    active = session.exec(
        select(PromptVersion).where(
            PromptVersion.pack == pack,
            PromptVersion.task_name == task.name,
            PromptVersion.active.is_(True),  # type: ignore[union-attr]
        )
    ).first()
    system = active.system_prompt if active else task.system_prompt
    instruction = active.instruction_template if active else task.instruction
    source = f"db:v{active.version}" if active else "code"
    if override:
        system = override.get("system_prompt") or system
        instruction = override.get("instruction_template") or instruction
        source = "override"
    return ResolvedPrompt(system, instruction, source)

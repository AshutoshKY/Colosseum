"""The task pack: model-neutral task definitions (prompt + mandatory schema + input builder)."""

from __future__ import annotations

from app.tasks.base import Task, TaskInput
from app.tasks.itemized_bills import ITEMIZED_BILLS

TASKS: dict[str, Task] = {ITEMIZED_BILLS.name: ITEMIZED_BILLS}

__all__ = ["Task", "TaskInput", "ITEMIZED_BILLS", "TASKS"]

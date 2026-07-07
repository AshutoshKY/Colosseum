"""The task pack: model-neutral task definitions (prompt + mandatory schema + input builder)."""

from __future__ import annotations

from app.tasks.base import Task, TaskInput
from app.tasks.itemized_bills import ITEMIZED_BILLS
from app.tasks.opd import (
    AUDIT_OPD,
    BENEFIT_PLAN,
    CONSOLIDATED_BILLS,
    ITEMS_CATEGORISATION,
    NME_ANALYSIS,
    OPD_TASKS,
    POLICY_EXTRACTION,
    SEGREGATION,
    merge_bills,
)

# All known tasks (itemized_bills from Phase 1 + the OPD pack). The OPD pack uses the same
# itemized_bills schema for its bills stage; the Phase-1 task is kept for back-compat.
TASKS: dict[str, Task] = {ITEMIZED_BILLS.name: ITEMIZED_BILLS, **OPD_TASKS}

__all__ = [
    "Task",
    "TaskInput",
    "TASKS",
    "ITEMIZED_BILLS",
    "OPD_TASKS",
    "SEGREGATION",
    "CONSOLIDATED_BILLS",
    "ITEMS_CATEGORISATION",
    "NME_ANALYSIS",
    "AUDIT_OPD",
    "POLICY_EXTRACTION",
    "BENEFIT_PLAN",
    "merge_bills",
]

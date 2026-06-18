"""The ``itemized_bills`` task — the Phase 1 vertical-slice task."""

from __future__ import annotations

from app.tasks.base import Task
from app.tasks.prompts.bills import (
    ITEMIZED_BILLS_INSTRUCTION,
    ITEMIZED_BILLS_SYSTEM_PROMPT,
)
from app.tasks.schemas.bills import ItemizedBillsOutput

ITEMIZED_BILLS = Task(
    name="itemized_bills",
    system_prompt=ITEMIZED_BILLS_SYSTEM_PROMPT,
    instruction=ITEMIZED_BILLS_INSTRUCTION,
    schema=ItemizedBillsOutput,
    requires_documents=True,
    document_types=frozenset({"itemized_bill", "bill"}),
)

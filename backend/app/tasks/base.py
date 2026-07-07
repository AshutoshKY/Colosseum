"""Task protocol: prompt + mandatory schema + input builder + document-type filter.

A ``Task`` is model-neutral. The runner pairs a task with a document + a model, then calls
``ModelGateway.structured`` using the task's system prompt, instruction, schema, and the
``DocumentInput`` list the task builds. ``requires_documents`` lets the capability gate decide
whether a text-only model is applicable (recorded as skipped, not failed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from app.providers.adapters import DocumentInput


@dataclass(frozen=True)
class TaskInput:
    """What a task needs from a document to run."""

    documents: list[DocumentInput]


@dataclass(frozen=True)
class Task:
    name: str
    system_prompt: str
    instruction: str
    schema: type[BaseModel]
    requires_documents: bool = True
    # 1-based page ranges to send by default (None = all pages). Lets us honor payload caps.
    default_page_ranges: str | None = None
    document_types: frozenset[str] = field(default_factory=frozenset)
    # Text-input tasks (items_categorisation, nme, policy_extraction, benefit_plan) consume a
    # prior stage's JSON rendered into the instruction via ``.format(**context)`` — no document.
    is_text_task: bool = False

    def build_input(self, document_path: str, *, page_ranges: str | None = None) -> TaskInput:
        return TaskInput(
            documents=[
                DocumentInput(
                    path=document_path,
                    page_ranges=page_ranges or self.default_page_ranges,
                    mime_type="application/pdf",
                )
            ]
        )

    def render_instruction(self, **context: object) -> str:
        """Fill the instruction template for text tasks (e.g. ``{bills_json}``)."""
        if not context:
            return self.instruction
        return self.instruction.format(**context)

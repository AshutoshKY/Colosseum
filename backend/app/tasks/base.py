"""Task protocol: prompt + mandatory schema + input builder + document-type filter.

A ``Task`` is model-neutral. The runner pairs a task with a document + a model, then calls
``ModelGateway.structured`` using the task's system prompt, instruction, schema, and the
``DocumentInput`` list the task builds. ``requires_documents`` lets the capability gate decide
whether a text-only model is applicable (recorded as skipped, not failed).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.providers.adapters import DocumentInput


@dataclass(frozen=True)
class TaskInput:
    """What a task needs from a document to run."""

    documents: list[DocumentInput]


@dataclass(frozen=True)
class ReferenceRuntime:
    model_id: str | None = None
    thinking_budget: int | None = None
    thinking_level: str | None = None
    max_output_tokens: int | None = None
    timeout_s: float | None = None


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
    depends_on: tuple[str, ...] = ()
    deterministic: bool = False
    reference_runtime: ReferenceRuntime = ReferenceRuntime()
    gold_feed_keys: tuple[str, ...] = ()

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

    def run_transform(self, upstream: dict[str, Any]) -> dict[str, Any]:
        """Run a deterministic task; deterministic task subclasses override this."""
        raise NotImplementedError(f"Task {self.name!r} has no deterministic transform")


@dataclass(frozen=True)
class TransformTask(Task):
    """A deterministic task backed by a small pure function."""

    transform: Callable[[dict[str, Any]], dict[str, Any]] = field(
        default=lambda upstream: upstream, repr=False
    )

    def run_transform(self, upstream: dict[str, Any]) -> dict[str, Any]:
        return self.transform(upstream)


class SubsetError(ValueError):
    """The requested task subset cannot form a valid execution plan."""


@dataclass(frozen=True)
class SubsetPlan:
    layers: list[list[str]]
    gold_requirements: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class TaskPack:
    name: str
    tasks: dict[str, Task]
    order: list[str]

    def __contains__(self, name: object) -> bool:
        return name in self.tasks

    def __getitem__(self, name: str) -> Task:
        return self.tasks[name]

    def __iter__(self):
        return iter(self.tasks)

    def dependency_graph(self) -> dict[str, tuple[str, ...]]:
        return {name: task.depends_on for name, task in self.tasks.items()}

    def resolve_subset(self, selected: list[str], upstream_mode: str) -> SubsetPlan:
        if upstream_mode not in {"gold", "model"}:
            raise SubsetError(f"Unknown upstream mode: {upstream_mode!r}")
        unknown = sorted(set(selected) - self.tasks.keys())
        if unknown:
            raise SubsetError(f"Unknown tasks: {', '.join(unknown)}")

        included = set(selected)

        missing_by_task = {
            name: tuple(dep for dep in self.tasks[name].depends_on if dep not in included)
            for name in included
        }
        if upstream_mode == "model":
            missing = sorted({dep for deps in missing_by_task.values() for dep in deps})
            if missing:
                raise SubsetError(f"Missing upstream tasks for model mode: {', '.join(missing)}")

        gold_requirements: dict[str, tuple[str, ...]] = {}
        if upstream_mode == "gold":
            for name, missing in missing_by_task.items():
                if missing:
                    task = self.tasks[name]
                    if task.gold_feed_keys and len(task.gold_feed_keys) == len(task.depends_on):
                        feed_by_dep = dict(zip(task.depends_on, task.gold_feed_keys, strict=True))
                        keys = tuple(feed_by_dep[dep] for dep in missing)
                    else:
                        keys = task.gold_feed_keys or missing
                    gold_requirements[name] = tuple(dict.fromkeys(keys))

        order_index = {name: i for i, name in enumerate(self.order)}
        indegree = {name: 0 for name in included}
        children: dict[str, list[str]] = {name: [] for name in included}
        for name in included:
            for dep in self.tasks[name].depends_on:
                if dep in included:
                    indegree[name] += 1
                    children[dep].append(name)

        layers: list[list[str]] = []
        remaining = set(included)
        while remaining:
            layer = sorted(
                (name for name in remaining if indegree[name] == 0),
                key=lambda name: (order_index.get(name, len(order_index)), name),
            )
            if not layer:
                raise SubsetError(f"Dependency cycle among tasks: {', '.join(sorted(remaining))}")
            layers.append(layer)
            remaining.difference_update(layer)
            for name in layer:
                for child in children[name]:
                    indegree[child] -= 1
        return SubsetPlan(layers=layers, gold_requirements=gold_requirements)

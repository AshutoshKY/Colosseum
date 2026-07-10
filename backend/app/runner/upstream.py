"""Resolve task inputs from live outputs first, then per-document ground truth."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import DocumentSample, GroundTruth


class MissingUpstreamData(LookupError):
    def __init__(self, task: str, document: DocumentSample) -> None:
        self.task = task
        self.document = document
        super().__init__(f"{task} for document {document.id} ({document.path})")


class UpstreamResolver:
    LEGACY_ALIASES = {
        "merge_bills": "upstream_bills",
        "benefits": "upstream_benefits",
    }

    def __init__(
        self,
        session: Session,
        document: DocumentSample,
        gold: dict[str, Any] | None = None,
        live_outputs: dict[str, Any] | None = None,
    ) -> None:
        self.document = document
        self.live_outputs = live_outputs if live_outputs is not None else {}
        self.gold = gold if gold is not None else self.load_gold(session, document.id)

    @staticmethod
    def load_gold(session: Session, document_id: int | None) -> dict[str, Any]:
        rows = session.exec(select(GroundTruth).where(GroundTruth.document_id == document_id)).all()
        tasks: dict[str, Any] = {}
        for row in rows:
            if isinstance(row.gold, dict) and isinstance(row.gold.get("tasks"), dict):
                tasks.update(row.gold["tasks"])
            else:
                tasks[row.task] = row.gold
        return {"tasks": tasks}

    def get(self, task_name: str) -> Any:
        if task_name in self.live_outputs:
            return self.live_outputs[task_name]
        tasks = self.gold.get("tasks", self.gold)
        if task_name in tasks:
            return tasks[task_name]
        alias = self.LEGACY_ALIASES.get(task_name)
        if alias and alias in tasks:
            return tasks[alias]
        raise MissingUpstreamData(task_name, self.document)

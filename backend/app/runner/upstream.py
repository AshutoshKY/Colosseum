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
        "upstream_bills": "merge_bills",
        "benefits": "upstream_benefits",
        "upstream_benefits": "benefits",
        "cheque_bank": "cheque_or_bank_details",
        "cheque_or_bank_details": "cheque_bank",
        "claim_form": "claim_forms",
        "claim_forms": "claim_form",
        "identity_document": "identity_documents",
        "identity_documents": "identity_document",
        "extract_icd_codes": "icd_codes",
        "icd_codes": "extract_icd_codes",
        "policy": "policy_extraction",
        "policy_extraction": "policy",
        "benefit_plan": "benefit_plan_selection",
        "benefit_plan_selection": "benefit_plan",
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
        # 1. Direct live output
        if task_name in self.live_outputs and self.live_outputs[task_name] is not None:
            return self.live_outputs[task_name]
        alias = self.LEGACY_ALIASES.get(task_name)
        if alias and alias in self.live_outputs and self.live_outputs[alias] is not None:
            return self.live_outputs[alias]

        # 2. Direct gold output
        tasks = self.gold.get("tasks", self.gold)
        if isinstance(tasks, dict):
            if task_name in tasks and tasks[task_name] is not None:
                return tasks[task_name]
            if alias and alias in tasks and tasks[alias] is not None:
                return tasks[alias]

        # 3. Dynamic synthesis for merge_bills
        if task_name in {"merge_bills", "upstream_bills"}:
            from app.tasks.opd import merge_bills

            itemized = self.live_outputs.get("itemized_bills") or (tasks.get("itemized_bills") if isinstance(tasks, dict) else None)
            consolidated = self.live_outputs.get("consolidated_bills") or (tasks.get("consolidated_bills") if isinstance(tasks, dict) else None)
            if itemized or consolidated:
                return merge_bills(itemized, consolidated)

        # 4. Dynamic synthesis for patient_summary
        if task_name == "patient_summary":
            from app.tasks.opd import _patient_summary_transform

            sources = {
                "claim_form": self.live_outputs.get("claim_form") or (tasks.get("claim_form") if isinstance(tasks, dict) else None),
                "prescription": self.live_outputs.get("prescription") or (tasks.get("prescription") if isinstance(tasks, dict) else None),
                "merge_bills": self.live_outputs.get("merge_bills") or (tasks.get("merge_bills") if isinstance(tasks, dict) else None) or (tasks.get("upstream_bills") if isinstance(tasks, dict) else None),
                "cheque_bank": self.live_outputs.get("cheque_bank") or (tasks.get("cheque_bank") if isinstance(tasks, dict) else None),
                "identity_document": self.live_outputs.get("identity_document") or (tasks.get("identity_document") if isinstance(tasks, dict) else None),
            }
            if any(sources.values()):
                return _patient_summary_transform(sources)

        raise MissingUpstreamData(task_name, self.document)


"""Prompts and compact task descriptions for LLM judging."""

from __future__ import annotations

import json
from typing import Any

MAX_JSON_CHARS = 50_000

TASK_DESCRIPTIONS = {
    "segregation": "Identify document types and their page ranges.",
    "policy_extraction": "Extract policy rules and non-medical-expense definitions.",
    "claim_form": "Extract patient, provider, and claim details from the claim form.",
    "prescription": "Extract diagnoses, complaints, and prescribed items.",
    "discharge_summary": "Extract hospitalization and clinical details.",
    "itemized_bills": "Extract itemized invoices and line items with amounts.",
    "consolidated_bills": "Extract consolidated invoices and their totals.",
    "merge_bills": "Combine itemized and consolidated bill outputs without losing data.",
    "items_categorisation": "Assign the correct claims category to every bill item.",
    "nme_analysis": "Calculate admissible and deductible amounts with reasons.",
    "identity_document": "Extract identity fields relevant to the patient.",
    "cheque_bank": "Extract bank or cheque payment details.",
    "extract_icd_codes": "Map clinical diagnoses and bill items to ICD codes.",
    "patient_summary": "Consolidate patient, hospitalization, clinical, and history data.",
    "benefit_plan": "Select applicable benefit plans and assign bill items.",
    "audit": "Audit the claim output for omissions, duplicates, and calculation errors.",
    "validation": "Validate claim completeness, consistency, and calculated amounts.",
}

GRADE_SYSTEM = """You are a senior health-claims QA auditor. Evaluate only the supplied
task and evidence. Penalize hallucinated values most heavily. Treat formatting-only or
semantically equivalent differences as acceptable_variant. Return concise, specific
field findings and an overall score from 0 to 1."""

DOC_GRADE_SYSTEM = """You are a senior health-claims QA auditor. Ground every finding in
the supplied claim document. Score faithfulness, completeness, and schema sanity. Penalize
hallucinations most heavily and do not infer facts absent from the document."""

RANK_SYSTEM = """You are a senior health-claims QA auditor comparing anonymized outputs.
Rank quality using faithfulness, completeness, and schema sanity. Penalize hallucinations
most heavily. Candidate names reveal no model identity. Ties are allowed only when quality
is indistinguishable."""


def _json(value: Any) -> str:
    rendered = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if len(rendered) <= MAX_JSON_CHARS:
        return rendered
    return rendered[:MAX_JSON_CHARS] + "\n...[truncated at 50,000 characters]"


def gold_grade_instruction(task: str, gold: Any, predicted: Any) -> str:
    return (
        f"TASK: {task}\nOBJECTIVE: {TASK_DESCRIPTIONS.get(task, task)}\n\n"
        f"GROUND TRUTH:\n{_json(gold)}\n\nCANDIDATE OUTPUT:\n{_json(predicted)}"
    )


def doc_grade_instruction(task: str, predicted: Any) -> str:
    return (
        f"TASK: {task}\nOBJECTIVE: {TASK_DESCRIPTIONS.get(task, task)}\n\n"
        f"CANDIDATE OUTPUT:\n{_json(predicted)}\n\n"
        "Use the attached source document as the sole factual reference."
    )


def ranking_instruction(task: str, candidates: dict[str, Any], gold: Any | None) -> str:
    evidence = (
        f"GROUND TRUTH:\n{_json(gold)}"
        if gold is not None
        else "Use the attached source document as the sole factual reference."
    )
    return (
        f"TASK: {task}\nOBJECTIVE: {TASK_DESCRIPTIONS.get(task, task)}\n\n{evidence}\n\n"
        f"ANONYMIZED CANDIDATES:\n{_json(candidates)}"
    )

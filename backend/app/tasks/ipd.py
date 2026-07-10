"""IPD task pack mirroring healthpay-ai@test-fhpl.

Fidelity differences retained deliberately:

* Colosseum enforces structured output through Instructor; healthpay parses the same
  schema-in-prompt JSON with json_repair and continuation loops.
* patient_summary is a pure transform over run/gold outputs instead of reading store-node
  rows from healthpay's database.
* insurer-specific NME rules are supplied through run/gold context when available.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.tasks.base import ReferenceRuntime, Task, TaskPack, TransformTask
from app.tasks.opd import merge_bills
from app.tasks.prompts.ipd_healthpay import (
    AUDIT_INSTRUCTION,
    BANK_DETAILS_EXTRACTOR,
    CLAIM_FORM_STRUCTURED_DATA_EXTRACTOR,
    CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR,
    DISCHARGE_SUMMARY_STRUCTURED_DATA_EXTRACTOR,
    DOCS_SEGREGATOR,
    DOCUMENT_INSTRUCTION,
    IDENTITY_DOCUMENT_EXTRACTOR,
    IPD_AUDIT_SYSTEM_PROMPT,
    ITEMS_CATEGORISATION_INSTRUCTION,
    ITEMS_CATEGORISATION_SYSTEM_PROMPT,
    NME_ANALYSIS_SYSTEM_PROMPT,
    NME_INSTRUCTION,
    PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR,
)
from app.tasks.schemas.ipd_healthpay import (
    BankDetailsOutput,
    DischargeSummaryOutput,
    IdentityDocumentOutput,
    IpdAuditOutput,
    IpdClaimFormOutput,
    IpdConsolidatedBillsOutput,
    IpdDocumentSegregatorResponse,
    IpdItemizedBillsOutput,
    IpdItemsCategorisationOutput,
    NMEAnalysisResponse,
    PatientSummaryData,
    ValidationScores,
)


def _merge(upstream: dict[str, Any]) -> dict[str, Any]:
    return merge_bills(upstream.get("itemized_bills"), upstream.get("consolidated_bills"))


def _patient_summary(upstream: dict[str, Any]) -> dict[str, Any]:
    claim = upstream.get("claim_form") or {}
    clinical = upstream.get("discharge_summary") or {}
    return {
        "patient_details": claim.get("part_a", claim),
        "hospitalization_details": claim.get("part_b", {}),
        "clinical_details": clinical.get("claims_digitization_details", clinical),
        "past_history_details": {},
        "bank_details": upstream.get("cheque_bank") or {},
        "identity_details": upstream.get("identity_document") or {},
    }


def _validation(upstream: dict[str, Any]) -> dict[str, Any]:
    bills = upstream.get("nme_analysis") or {}
    total = 0.0
    admissible = 0.0
    items = bills.get("items") or bills.get("nme_list") or []
    for wrapped in items:
        item = wrapped.get("nme_item", wrapped)
        total += float(item.get("bill_amount") or 0)
        admissible += float(item.get("admissible_amount") or item.get("bill_amount") or 0)
    return {
        "bill_total": round(total, 2),
        "admissible_total": round(admissible, 2),
        "patient_summary_complete": bool(upstream.get("patient_summary")),
    }


SEGREGATION = Task(
    "segregation",
    DOCS_SEGREGATOR,
    DOCUMENT_INSTRUCTION,
    IpdDocumentSegregatorResponse,
    reference_runtime=ReferenceRuntime(model_id="gemini-3-flash", thinking_level="low"),
)
DISCHARGE_SUMMARY = Task(
    "discharge_summary",
    DISCHARGE_SUMMARY_STRUCTURED_DATA_EXTRACTOR,
    DOCUMENT_INSTRUCTION,
    DischargeSummaryOutput,
    document_types=frozenset({"discharge_summary", "consolidated_bill"}),
    depends_on=("segregation",),
    reference_runtime=ReferenceRuntime(model_id="gemini-3-flash", thinking_level="minimal"),
    gold_feed_keys=("segregation",),
)
ITEMIZED_BILLS = Task(
    "itemized_bills",
    PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR,
    DOCUMENT_INSTRUCTION,
    IpdItemizedBillsOutput,
    document_types=frozenset({"itemized_bill"}),
    depends_on=("segregation",),
    reference_runtime=ReferenceRuntime(model_id="gemini-2.5-flash", thinking_budget=8000),
    gold_feed_keys=("segregation",),
)
CONSOLIDATED_BILLS = Task(
    "consolidated_bills",
    CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR,
    DOCUMENT_INSTRUCTION,
    IpdConsolidatedBillsOutput,
    document_types=frozenset({"consolidated_bill"}),
    depends_on=("segregation",),
    reference_runtime=ReferenceRuntime(model_id="gemini-2.5-flash", thinking_budget=8000),
    gold_feed_keys=("segregation",),
)
MERGE_BILLS = TransformTask(
    "merge_bills",
    "",
    "",
    IpdItemizedBillsOutput,
    requires_documents=False,
    depends_on=("itemized_bills", "consolidated_bills"),
    deterministic=True,
    gold_feed_keys=("itemized_bills", "consolidated_bills"),
    transform=_merge,
)
ITEMS_CATEGORISATION = Task(
    "items_categorisation",
    ITEMS_CATEGORISATION_SYSTEM_PROMPT,
    ITEMS_CATEGORISATION_INSTRUCTION,
    IpdItemsCategorisationOutput,
    requires_documents=False,
    is_text_task=True,
    depends_on=("merge_bills",),
    reference_runtime=ReferenceRuntime(model_id="gemini-2.5-flash", thinking_budget=8000),
    gold_feed_keys=("merge_bills",),
)
NME_ANALYSIS = Task(
    "nme_analysis",
    NME_ANALYSIS_SYSTEM_PROMPT,
    NME_INSTRUCTION,
    NMEAnalysisResponse,
    requires_documents=False,
    is_text_task=True,
    depends_on=("items_categorisation",),
    reference_runtime=ReferenceRuntime(model_id="gemini-2.5-flash", thinking_budget=8000),
    gold_feed_keys=("items_categorisation",),
)
CLAIM_FORM = Task(
    "claim_form",
    CLAIM_FORM_STRUCTURED_DATA_EXTRACTOR,
    DOCUMENT_INSTRUCTION,
    IpdClaimFormOutput,
    document_types=frozenset({"claim_forms"}),
    depends_on=("segregation",),
    reference_runtime=ReferenceRuntime(model_id="gemini-2.5-flash", thinking_budget=0),
    gold_feed_keys=("segregation",),
)
IDENTITY_DOCUMENT = Task(
    "identity_document",
    IDENTITY_DOCUMENT_EXTRACTOR,
    DOCUMENT_INSTRUCTION,
    IdentityDocumentOutput,
    document_types=frozenset({"identity_document"}),
    depends_on=("segregation", "claim_form"),
    reference_runtime=ReferenceRuntime(model_id="gemini-2.5-flash", thinking_budget=0),
    gold_feed_keys=("segregation", "claim_form"),
)
CHEQUE_BANK = Task(
    "cheque_bank",
    BANK_DETAILS_EXTRACTOR,
    DOCUMENT_INSTRUCTION,
    BankDetailsOutput,
    document_types=frozenset({"cheque_or_bank_details"}),
    depends_on=("segregation",),
    reference_runtime=ReferenceRuntime(model_id="gemini-3-flash", thinking_budget=0),
    gold_feed_keys=("segregation",),
)
PATIENT_SUMMARY = TransformTask(
    "patient_summary",
    "",
    "",
    PatientSummaryData,
    requires_documents=False,
    depends_on=("claim_form", "discharge_summary", "cheque_bank", "identity_document"),
    deterministic=True,
    gold_feed_keys=("claim_form", "discharge_summary", "cheque_bank", "identity_document"),
    transform=_patient_summary,
)
AUDIT = Task(
    "audit",
    IPD_AUDIT_SYSTEM_PROMPT,
    AUDIT_INSTRUCTION,
    IpdAuditOutput,
    depends_on=("nme_analysis", "patient_summary", "segregation"),
    reference_runtime=ReferenceRuntime(
        model_id="gemini-3.1-pro",
        thinking_level="medium",
        max_output_tokens=16000,
        timeout_s=300,
    ),
    gold_feed_keys=("nme_analysis", "patient_summary", "segregation"),
)
VALIDATION = TransformTask(
    "validation",
    "",
    "",
    ValidationScores,
    requires_documents=False,
    depends_on=("nme_analysis", "patient_summary", "segregation"),
    deterministic=True,
    gold_feed_keys=("nme_analysis", "patient_summary", "segregation"),
    transform=_validation,
)

IPD_PIPE_ORDER = [
    "segregation",
    "discharge_summary",
    "itemized_bills",
    "consolidated_bills",
    "claim_form",
    "cheque_bank",
    "identity_document",
    "merge_bills",
    "items_categorisation",
    "nme_analysis",
    "patient_summary",
    "audit",
    "validation",
]
IPD_TASKS = {
    task.name: task
    for task in (
        SEGREGATION,
        DISCHARGE_SUMMARY,
        ITEMIZED_BILLS,
        CONSOLIDATED_BILLS,
        CLAIM_FORM,
        CHEQUE_BANK,
        IDENTITY_DOCUMENT,
        MERGE_BILLS,
        ITEMS_CATEGORISATION,
        NME_ANALYSIS,
        PATIENT_SUMMARY,
        AUDIT,
        VALIDATION,
    )
}


def get_ipd_pack(variant: str | None = None) -> TaskPack:
    normalized = (variant or "CL").upper()
    if normalized not in {"CL", "RM", "PP"}:
        raise KeyError(f"Unknown IPD variant: {variant!r}")
    tasks = dict(IPD_TASKS)
    order = list(IPD_PIPE_ORDER)
    if normalized == "PP":
        tasks.pop("consolidated_bills")
        order.remove("consolidated_bills")
        tasks["merge_bills"] = replace(
            tasks["merge_bills"],
            depends_on=("itemized_bills",),
            gold_feed_keys=("itemized_bills",),
        )
    return TaskPack(name="IPD", tasks=tasks, order=order)

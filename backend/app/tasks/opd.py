"""OPD task pack — Phase 2.5: the five healthpay agents re-vendored from healthpay-ai
(segregation, itemized_bills, items_categorisation, nme, audit) + benefit_plan/policy_extraction
from superclaims-ai, with full verbatim prompts and faithful schemas.

Document tasks (segregation, itemized_bills, consolidated_bills, audit) take the claim PDF
(native for Gemini/Claude, rasterized for vision-only models). Text tasks (items_categorisation,
nme, policy_extraction, benefit_plan) consume a prior stage's structured JSON via the
instruction template (``is_text_task=True``) — no document, so text-only models participate.

PIPE ORDER (the production OPD dependency order):
  segregation -> (policy_extraction) -> itemized_bills -> consolidated_bills -> merge_bills
    -> items_categorisation (<- merged bills)
    -> nme (<- categorised items)
    -> benefit_plan (<- categorised items + benefits)
    -> audit (<- assembled JSON + claimed amount)

The explicit upstream->downstream wiring lives in ``build_text_inputs`` so a single document can
flow end-to-end through the pack for one model.

``merge_bills`` is the deterministic (non-LLM) ``merge_bills`` node: it concatenates consolidated
+ itemized bill groups into one bills array (consolidated first, mirroring healthpay
``bill_merger_node``) and assigns the per-item ``s.no.`` the text tasks key on, plus ``bill_id``.
``prepare_categorisation_input`` / ``prepare_nme_input`` mirror healthpay
``models/llm_input_models.py`` (slim payloads keyed by bill_id + s.no.).
"""

from __future__ import annotations

import json
from typing import Any

from app.tasks.base import Task
from app.tasks.prompts.opd_healthpay import (
    AUDIT_OPD_INSTRUCTION,
    AUDIT_SYSTEM_PROMPT_OPD,
    BENEFIT_PLAN_INSTRUCTION,
    BENEFIT_PLAN_SYSTEM_PROMPT,
    CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR,
    CONSOLIDATED_BILL_SYSTEM_PROMPT,
    CONSOLIDATED_BILLS_INSTRUCTION,
    ITEMIZED_BILLS_INSTRUCTION,
    ITEMS_CATEGORISATION_INSTRUCTION,
    ITEMS_CATEGORISATION_SYSTEM_PROMPT,
    NME_ANALYSIS_INSTRUCTION_TEXT,
    NME_ANALYSIS_SYSTEM_PROMPT,
    PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR,
    PHARMACY_SYSTEM_PROMPT,
    POLICY_EXTRACTION_INSTRUCTION,
    POLICY_EXTRACTION_SYSTEM_PROMPT,
    SEGREGATION_INSTRUCTION,
    SEGREGATION_PROMPT,
)
from app.tasks.schemas.opd_healthpay import (
    AuditAnalysisOutput,
    BenefitPlanSelectionOutput,
    ConsolidatedBillsOutput,
    DocumentSegregatorResponse,
    EkincarePolicyExtractionOutput,
    ItemizedBillsOutput,
    ItemsCategorisationOutput,
    NMEAnalysisResponse,
)

# ---------------------------------------------------------------------------
# Document tasks
# ---------------------------------------------------------------------------
SEGREGATION = Task(
    name="segregation",
    # The healthpay segregation system prompt is short; the full instruction body is the
    # DOCS_SEGREGATOR block. Keep both so the model sees the complete classification framework.
    system_prompt=SEGREGATION_PROMPT,
    instruction=SEGREGATION_INSTRUCTION,
    schema=DocumentSegregatorResponse,
    requires_documents=True,
    document_types=frozenset(),  # runs on the whole packet
)

ITEMIZED_BILLS = Task(
    name="itemized_bills",
    system_prompt=PHARMACY_SYSTEM_PROMPT + "\n" + PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR,
    instruction=ITEMIZED_BILLS_INSTRUCTION,
    schema=ItemizedBillsOutput,
    requires_documents=True,
    document_types=frozenset({"itemized_bill"}),
)

CONSOLIDATED_BILLS = Task(
    name="consolidated_bills",
    system_prompt=CONSOLIDATED_BILL_SYSTEM_PROMPT + "\n" + CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR,
    instruction=CONSOLIDATED_BILLS_INSTRUCTION,
    schema=ConsolidatedBillsOutput,
    requires_documents=True,
    document_types=frozenset({"consolidated_bill"}),
)

AUDIT_OPD = Task(
    name="audit",
    # System prompt is filled per-document by ``build_audit_prompt`` at runtime; the static
    # template here is a sane default for offline introspection/tests.
    system_prompt=AUDIT_SYSTEM_PROMPT_OPD,
    instruction=AUDIT_OPD_INSTRUCTION,
    schema=AuditAnalysisOutput,
    requires_documents=True,
)

# ---------------------------------------------------------------------------
# Text tasks (consume prior-stage JSON)
# ---------------------------------------------------------------------------
ITEMS_CATEGORISATION = Task(
    name="items_categorisation",
    system_prompt=ITEMS_CATEGORISATION_SYSTEM_PROMPT,
    instruction=ITEMS_CATEGORISATION_INSTRUCTION,
    schema=ItemsCategorisationOutput,
    requires_documents=False,
    is_text_task=True,
)

NME_ANALYSIS = Task(
    name="nme_analysis",
    system_prompt=NME_ANALYSIS_SYSTEM_PROMPT,
    instruction=NME_ANALYSIS_INSTRUCTION_TEXT,
    schema=NMEAnalysisResponse,
    requires_documents=False,
    is_text_task=True,
)

POLICY_EXTRACTION = Task(
    name="policy_extraction",
    system_prompt=POLICY_EXTRACTION_SYSTEM_PROMPT,
    instruction=POLICY_EXTRACTION_INSTRUCTION,
    schema=EkincarePolicyExtractionOutput,
    requires_documents=False,
    is_text_task=True,
)

BENEFIT_PLAN = Task(
    name="benefit_plan",
    system_prompt=BENEFIT_PLAN_SYSTEM_PROMPT,
    instruction=BENEFIT_PLAN_INSTRUCTION,
    schema=BenefitPlanSelectionOutput,
    requires_documents=False,
    is_text_task=True,
)


# ---------------------------------------------------------------------------
# merge_bills — deterministic transform (non-LLM), mirrors healthpay bill_merger_node.
# ---------------------------------------------------------------------------
def merge_bills(
    itemized: dict[str, Any] | None, consolidated: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge itemized + consolidated bill outputs into one ``bills`` array.

    Mirrors healthpay ``bill_merger_node`` (consolidated first, then itemized) and assigns a
    1-based per-item ``s.no.`` (the key the text tasks reference) plus a ``bill_id`` on each
    group (derived from the bill invoice number) and a ``source`` tag. Pure function.
    """
    merged: list[dict[str, Any]] = []
    counter = 0
    for source, payload in (("consolidated", consolidated), ("itemized", itemized)):
        if not payload:
            continue
        for group in payload.get("bills", []) or []:
            bill = dict(group.get("bill") or {})
            counter += 1
            bill_id = bill.get("bill_id") or bill.get("invoice_number") or f"BILL-{counter}"
            bill["bill_id"] = bill_id
            items = []
            for i, item in enumerate(group.get("items", []) or [], start=1):
                item = dict(item)
                item["s.no."] = i
                items.append(item)
            merged.append({"bill": bill, "items": items, "source": source})
    return {"bills": merged}


def prepare_categorisation_input(bill_data: dict[str, Any]) -> dict[str, Any]:
    """Slim merged bills to only the fields items_categorisation needs (bill_id, ip_number,
    facility name, per-item s.no. + item_name). Mirrors healthpay
    ``prepare_categorization_input``."""
    slim_bills = []
    for entry in bill_data.get("bills", []) or []:
        bill_meta = entry.get("bill", {}) or {}
        items = entry.get("items", []) or []
        slim_bills.append(
            {
                "bill": {
                    "bill_id": bill_meta.get("bill_id") or bill_meta.get("invoice_number"),
                    "ip_number": bill_meta.get("ip_number"),
                    "facility_details": {"name": (bill_meta.get("facility_details") or {}).get("name")},
                },
                "items": [
                    {"s.no.": it.get("s.no."), "item_name": it.get("item_name", "")} for it in items
                ],
            }
        )
    return {"bills": slim_bills}


def apply_categories(bill_data: dict[str, Any], categorised: dict[str, Any]) -> dict[str, Any]:
    """Merge items_categorisation output back onto the merged bills (matching by bill_id + s.no.),
    so NME sees ``category`` + ``final_amount`` per item. Mirrors the production flow where the
    categorised bills feed NME."""
    cat_by_bill: dict[str, dict[int, str]] = {}
    for grp in categorised.get("bill_item_categories", []) or []:
        bid = grp.get("bill_id")
        per_item: dict[int, str] = {}
        for ci in grp.get("categorized_items", []) or []:
            sno = ci.get("s.no.") if "s.no." in ci else ci.get("serial_no")
            if sno is not None:
                per_item[int(sno)] = ci.get("category", "Others")
        if bid is not None:
            cat_by_bill[bid] = per_item

    out: dict[str, Any] = {"bills": []}
    for entry in bill_data.get("bills", []) or []:
        bill_meta = entry.get("bill", {}) or {}
        bid = bill_meta.get("bill_id")
        per_item = cat_by_bill.get(bid, {})
        new_items = []
        for it in entry.get("items", []) or []:
            it = dict(it)
            sno = it.get("s.no.")
            if sno is not None and int(sno) in per_item:
                it["category"] = per_item[int(sno)]
            new_items.append(it)
        out["bills"].append({"bill": bill_meta, "items": new_items, "source": entry.get("source")})
    return out


def prepare_nme_input(bill_data: dict[str, Any]) -> dict[str, Any]:
    """Slim categorised bills to only NME-relevant fields (bill_id, s.no., item_name, category,
    final_amount) and drop returned items. Mirrors healthpay ``prepare_nme_analysis_input``."""
    slim_bills = []
    for entry in bill_data.get("bills", []) or []:
        bill_meta = entry.get("bill", {}) or {}
        slim_items = []
        for it in entry.get("items", []) or []:
            if it.get("is_returned") is True:
                continue
            slim_items.append(
                {
                    "s.no.": it.get("s.no."),
                    "item_name": it.get("item_name", ""),
                    "category": it.get("category"),
                    "final_amount": it.get("final_amount"),
                }
            )
        slim_bills.append(
            {"bill": {"bill_id": bill_meta.get("bill_id") or bill_meta.get("invoice_number")}, "items": slim_items}
        )
    return {"bills": slim_bills}


def calculated_total(bill_data: dict[str, Any]) -> float:
    """Sum of item final_amounts across merged bills (the audit's calculated_total)."""
    total = 0.0
    for entry in bill_data.get("bills", []) or []:
        for it in entry.get("items", []) or []:
            try:
                total += float(it.get("net_amount") or it.get("final_amount") or 0)
            except (TypeError, ValueError):
                continue
    return round(total, 2)


def build_text_inputs(
    *,
    itemized: dict[str, Any] | None,
    consolidated: dict[str, Any] | None,
    categorised: dict[str, Any] | None = None,
    policy_context: dict[str, Any] | None = None,
    benefits: list[dict[str, Any]] | None = None,
    claimed_amount: float | int = 0,
) -> dict[str, str]:
    """Build the rendered instruction for each text task, wiring the upstream structured output.

    items_categorisation <- merged bills
    nme                  <- categorised items (falls back to merged bills if categorisation absent)
    benefit_plan         <- categorised items + benefits + policy context
    policy_extraction    <- policy context payload
    """
    merged = merge_bills(itemized, consolidated)
    policy_context = policy_context or {}

    cat_input = prepare_categorisation_input(merged)

    # NME / benefit_plan prefer the categorised bills (s.no. + category + final_amount).
    nme_source = apply_categories(merged, categorised) if categorised else merged
    nme_input = prepare_nme_input(nme_source)

    benefit_context = {
        "bills": nme_source["bills"],
        "benefits": benefits or [],
        "policy_context": policy_context,
        "clinical_context": {},
    }

    return {
        "items_categorisation": ITEMS_CATEGORISATION.render_instruction(bills_json=json.dumps(cat_input)),
        "nme_analysis": NME_ANALYSIS.render_instruction(bills_json=json.dumps(nme_input)),
        "policy_extraction": POLICY_EXTRACTION.render_instruction(policy_context=json.dumps(policy_context)),
        "benefit_plan": BENEFIT_PLAN.render_instruction(benefit_context=json.dumps(benefit_context)),
    }


OPD_TASKS: dict[str, Task] = {
    t.name: t
    for t in (
        SEGREGATION,
        POLICY_EXTRACTION,
        ITEMIZED_BILLS,
        CONSOLIDATED_BILLS,
        ITEMS_CATEGORISATION,
        NME_ANALYSIS,
        BENEFIT_PLAN,
        AUDIT_OPD,
    )
}

# Pipe order (production OPD dependency order). policy_extraction is a text task; it is run
# in the text phase but conceptually precedes the bills extraction.
OPD_PIPE_ORDER: list[str] = [
    "segregation",
    "policy_extraction",
    "itemized_bills",
    "consolidated_bills",
    "items_categorisation",
    "nme_analysis",
    "benefit_plan",
    "audit",
]

# Document-driven tasks the smoke runs directly on the claim PDF.
OPD_DOCUMENT_TASKS: list[str] = ["segregation", "itemized_bills", "consolidated_bills", "audit"]
OPD_TEXT_TASKS: list[str] = [
    "policy_extraction",
    "items_categorisation",
    "nme_analysis",
    "benefit_plan",
]

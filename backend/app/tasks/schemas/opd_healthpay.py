"""OPD schemas vendored faithfully from healthpay-ai ``models/*`` (+ superclaims for benefit_plan).

Phase 2.5 correction: the five healthpay agents (segregation, itemized_bills,
items_categorisation, nme, audit) get their schemas from the healthpay sources, and benefit_plan
from superclaims ``schemas/ekincare.py``. Structured output stays MANDATORY — field names,
aliases, enums, and defaults are preserved so cross-model comparison runs against the exact
contract the production pipeline uses.

Provenance:
  DocumentSegregatorResponse  -> healthpay  models/document_segregator.py
  PharmacyBillStructuredData   -> healthpay  models/pharmacy_bill.py
  ItemsCategorisationOutput    -> healthpay  prompts/bills.py output schema (bill_item_categories)
  NMEAnalysisResponse          -> healthpay  models/nme_analysis.py (+ prompt nme_list shape)
  AuditAnalysisOutput          -> healthpay  prompts/audit.py output_schema (reused from schemas/opd.py)
  BenefitPlanSelectionOutput   -> superclaims schemas/ekincare.py
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Reuse the already-vendored audit/benefit_plan/policy schemas (they faithfully match the
# healthpay audit output_schema and the superclaims ekincare benefit/policy schemas).
from app.tasks.schemas.opd import (  # noqa: F401
    AuditAnalysisOutput,
    BenefitItemAssignment,
    BenefitPlanSelectionOutput,
    EkincarePolicyExtractionOutput,
    PlanApplicability,
)

# ---------------------------------------------------------------------------
# segregation — healthpay models/document_segregator.py (DocumentSegregatorResponse).
# The prompt emits the optional ``is_pharmacy_bill`` flag on itemized_bill segments; the
# healthpay model derives that downstream, so we add it as an optional field here to capture it
# without breaking the model-neutral structured output.
# ---------------------------------------------------------------------------
DocumentType = Literal[
    "claim_forms",
    "cheque_or_bank_details",
    "identity_document",
    "itemized_bill",
    "consolidated_bill",
    "discharge_summary",
    "prescription",
    "investigation_report",
    "cash_receipt",
    "other",
]


class DocumentSegment(BaseModel):
    document_type: DocumentType = Field(description="Type of document from predefined categories")
    pages: str = Field(description="Compact page range string such as '1-3,5,8-10'")
    is_pharmacy_bill: bool | None = Field(
        default=None,
        description="Only present for itemized_bill segments; true for standalone pharmacy bills.",
    )


class DocumentSegregatorResponse(BaseModel):
    segments: list[DocumentSegment] = Field(description="List of document segments")


# ---------------------------------------------------------------------------
# itemized_bills + consolidated_bills — healthpay models/pharmacy_bill.py shape, expressed
# as the {"bills": [{"bill": {...}, "items": [...]}]} structure the prompts + downstream
# merge_bills/items_categorisation expect (the production extractor emits this nested form,
# not the flat PharmacyBillItem list).
# ---------------------------------------------------------------------------
class FacilityDetails(BaseModel):
    name: str | None = Field(default=None)
    registration_number: str | None = Field(default=None)


class BillHeader(BaseModel):
    invoice_number: str | None = Field(default=None, description="Bill or invoice number")
    ip_number: str | None = Field(default=None, description="In-Patient/ER/DG number if available")
    bill_date: str | None = Field(default=None, description="Date of the bill (YYYY-MM-DD)")
    total_discount: float | None = Field(
        default=None, description="Bill-level discount total (Discount/Less/Rebate/Concession)."
    )
    net_amount: float | None = Field(
        default=None, description="Bill-level net/payable total AFTER discount."
    )
    page_number: int | None = Field(default=None)
    facility_details: FacilityDetails | None = Field(default=None)


class ItemizedBillItem(BaseModel):
    item_name: str = Field(description="Name or description of the product or service")
    brand_name: str | None = Field(default=None)
    generic_name: str | None = Field(default=None)
    unit_price: float | None = Field(default=None, description="Per-unit/rate/MRP price when shown.")
    quantity: float | None = Field(default=None, description="Quantity of the item")
    discount: float | None = Field(default=None, description="Discount amount for the item")
    final_amount: float = Field(
        description=(
            "STRICT: gross/listed TOTAL LINE AMOUNT before discount. Use printed line total, or "
            "unit_price * quantity if no line total is printed. NEVER the post-discount value."
        )
    )
    net_amount: float | None = Field(default=None, description="Item amount after discount if shown.")
    is_returned: bool | None = Field(default=None)


class ItemizedBillGroup(BaseModel):
    bill: BillHeader
    items: list[ItemizedBillItem]


class ItemizedBillsOutput(BaseModel):
    bills: list[ItemizedBillGroup]


class ConsolidatedBillItem(BaseModel):
    item_name: str
    unit_price: float | None = Field(default=None, description="Per-unit/rate price when shown.")
    quantity: float | None = Field(default=None)
    discount: float | None = Field(default=None)
    final_amount: float = Field(
        description=(
            "STRICT: gross/listed TOTAL LINE AMOUNT before any discount. Use the ORIGINAL "
            "(larger) amount when both original and discounted are shown."
        )
    )
    net_amount: float | None = Field(default=None)
    is_returned: bool | None = Field(default=None)


class ConsolidatedBillGroup(BaseModel):
    bill: BillHeader
    items: list[ConsolidatedBillItem]


class ConsolidatedBillsOutput(BaseModel):
    bills: list[ConsolidatedBillGroup]


# ---------------------------------------------------------------------------
# items_categorisation — healthpay prompts/bills.py output schema (bill_item_categories).
# Keys ``s.no.`` and ``bill_id`` preserved via aliases (downstream NME keys on these).
# ---------------------------------------------------------------------------
class BillCategoryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    serial_no: int = Field(alias="s.no.", description="From the input item.s.no.")
    category: str = Field(description="The determined main category")


class BillItemCategoryGroup(BaseModel):
    bill_id: str = Field(description="From the input bill.bill_id")
    categorized_items: list[BillCategoryItem] = Field(default_factory=list)


class ItemsCategorisationOutput(BaseModel):
    bill_item_categories: list[BillItemCategoryGroup] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# nme — healthpay models/nme_analysis.py + the prompt's nme_list/nme_item shape.
# The production prompt emits {"nme_list": [{"nme_item": {"sr.no", ...}}]}; we vendor that
# exact shape (alias ``sr.no``) so structured output matches the contract.
# ---------------------------------------------------------------------------
class NmeItemDetails(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    serial_no: int = Field(alias="sr.no", description="Serial number")
    item_name: str = Field(description="Item name or description")
    bill_amount: float = Field(description="Total bill amount for the item in INR")
    deduction_reason: str = Field(description="Reason for deduction from the NME list")


class NmeListItem(BaseModel):
    nme_item: NmeItemDetails


class NMEAnalysisResponse(BaseModel):
    nme_list: list[NmeListItem] = Field(default_factory=list)

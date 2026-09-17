# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/adjudication.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BenefitPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable_benefits: list[dict[str, str | float | None]]
    payable_amount: float | None
    deductions: list[dict[str, str | float | None]]
    rationale: str | None


class PatientSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_summary: dict[str, Any]


class AuditPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["DELETE_BILL", "DELETE_ITEM", "EDIT_BILL_DETAILS", "EDIT_ITEM", "ADD_BILL", "ADD_ITEM"]
    bill_id: str | None
    item_s_no: int | None
    reason: str | None
    page_reference: str | None
    impact: str | None
    bill_invoice_number: str | None
    bill_net_amount: float | None
    key: str | None
    old_value: Any
    new_value: Any
    calculation: str | None
    bill_data: dict[str, Any] | None
    item_data: dict[str, Any] | None


class BillAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_total_of_bills: float
    corrected_total_of_bills: float
    discrepancy_amount: float
    bills_analyzed: int
    duplicates_found: int
    bills_with_corrections: int
    mathematical_consistency: bool | None
    patches: list[AuditPatch]


class FhplAuditPatch(BaseModel):
    """FHPL IPD patches: bill fixes + patient-summary fixes (incl. claimed amount)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "DELETE_BILL",
        "DELETE_ITEM",
        "EDIT_BILL_DETAILS",
        "EDIT_ITEM",
        "ADD_BILL",
        "ADD_ITEM",
        "EDIT_CLAIMED_AMOUNT",
        "EDIT_PATIENT_SUMMARY",
    ]
    bill_id: str | None = None
    item_s_no: int | None = None
    reason: str | None = None
    page_reference: str | None = None
    impact: str | None = None
    bill_invoice_number: str | None = None
    bill_net_amount: float | None = None
    key: str | None = None
    # Required (may be null for DELETE_*). Optional defaults let structured output omit
    # new_value, which breaks EDIT_PATIENT_SUMMARY / EDIT_* in the review UI.
    old_value: Any
    new_value: Any
    calculation: str | None = None
    bill_data: dict[str, Any] | None = None
    item_data: dict[str, Any] | None = None
    new_amount: float | None = None
    old_amount: float | None = None


class FhplAuditAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_claimed_amount: float
    original_total_of_bills: float
    updated_claimed_amount: float
    true_total_of_bills: float
    discrepancy_amount: float
    status: Literal["MATCH", "OVERCLAIMED", "UNDERCLAIMED", "NO CLAIM AMOUNT FOUND"]
    discrepancy_reason: str | None = None
    bills_analyzed: int
    duplicates_found: int
    bills_with_corrections: int
    fwa_flags: list[str] = Field(default_factory=list)


class FhplAuditValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mathematical_consistency: bool | None = None
    all_duplicates_found: bool | None = None
    claim_amount_verified: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class FhplAuditOutput(BaseModel):
    """FHPL IPD audit: bill + patient-summary corrections (v1 / review UI shape)."""

    model_config = ConfigDict(extra="forbid")

    analysis: FhplAuditAnalysis
    patches: list[FhplAuditPatch]
    validation: FhplAuditValidation


class ValidationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    warnings: list[str]
    errors: list[str]
    bills_score: float = Field(ge=0.0, le=100.0)
    claimed_amount: float = Field(ge=0.0)
    claimed_amount_score: float = Field(ge=0.0, le=100.0)
    categorization_score: float = Field(ge=0.0, le=100.0)
    effective_categorization_score: float = Field(ge=0.0, le=100.0)
    amount_score: float
    amount_difference: float
    is_negative: bool
    is_diff_same_as_consol_dis: bool
    recalculated_amount_score: float
    recalculated_difference: float
    contains_handwritten_bill: bool
    printed_bills_percentage: float = Field(ge=0.0, le=100.0)

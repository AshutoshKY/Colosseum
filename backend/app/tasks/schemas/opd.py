"""OPD adjudication schemas — audit / benefit_plan / policy_extraction (mandatory structured output).

Phase 2.5: the segregation / bills / items_categorisation / nme schemas were re-vendored from
healthpay-ai and now live in ``schemas/opd_healthpay.py``. This module keeps only the
adjudication schemas, which come from superclaims-ai:
  - ``schemas/adjudication.py`` -> AuditAnalysisOutput (+ nested)  [healthpay audit output_schema shape]
  - ``schemas/ekincare.py``     -> BenefitPlanSelectionOutput, EkincarePolicyExtractionOutput (+ nested)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# audit (adjudication) — healthpay prompts/audit.py output_schema (OPD).
# ---------------------------------------------------------------------------
class AuditFlaggedItem(BaseModel):
    item_name: str | None = Field(default=None)
    bill_id: str | None = Field(default=None)
    flag_reason: str | None = Field(default=None)
    recommendation: str | None = Field(default=None)


class AuditMedicalLegibility(BaseModel):
    prescription_bill_match: bool | None = Field(default=None)
    diagnosis_treatment_consistent: bool | None = Field(default=None)
    flagged_items: list[AuditFlaggedItem] = Field(default_factory=list)
    summary: str | None = Field(default=None)


class AuditPolicyViolation(BaseModel):
    rule_name: str | None = Field(default=None)
    item_name: str | None = Field(default=None)
    bill_id: str | None = Field(default=None)
    item_s_no: int | None = Field(default=None)
    violation_details: str | None = Field(default=None)
    amount_impacted: float = Field(default=0.0)
    recommendation: str | None = Field(default=None)


class AuditIcdCode(BaseModel):
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    diagnosis: str | None = Field(default=None)
    description: str | None = Field(default=None)
    chapter: str | None = Field(default=None)
    block: str | None = Field(default=None)
    source: str | None = Field(default=None)
    type: str | None = Field(default=None)
    related_bill_ids: list[str] = Field(default_factory=list)


class AuditPatch(BaseModel):
    type: str = Field(...)
    bill_id: str | None = Field(default=None)
    item_s_no: int | None = Field(default=None)
    reason: str | None = Field(default=None)
    page_reference: str | None = Field(default=None)
    impact: str | None = Field(default=None)
    bill_invoice_number: str | None = Field(default=None)
    bill_net_amount: float | None = Field(default=None)
    key: str | None = Field(default=None)
    old_value: Any = Field(default=None)
    new_value: Any = Field(default=None)
    calculation: str | None = Field(default=None)
    bill_data: dict[str, Any] | None = Field(default=None)
    item_data: dict[str, Any] | None = Field(default=None)
    new_amount: float | None = Field(default=None)
    old_amount: float | None = Field(default=None)
    flag_type: str | None = Field(default=None)
    recommendation: str | None = Field(default=None)


class AuditAnalysisOutput(BaseModel):
    # Common fields (IPD + OPD)
    original_claimed_amount: float = Field(default=0.0)
    original_total_of_bills: float = Field(default=0.0)
    updated_claimed_amount: float = Field(default=0.0)
    true_total_of_bills: float = Field(default=0.0)
    discrepancy_amount: float = Field(default=0.0)
    status: str = Field(default="MATCH")
    discrepancy_reason: str | None = Field(default=None)
    bills_analyzed: int = Field(default=0)
    duplicates_found: int = Field(default=0)
    bills_with_corrections: int = Field(default=0)
    patches_applied: int = Field(default=0)

    # OPD-specific fields
    medical_legibility_issues: int = Field(default=0)
    policy_violations_count: int = Field(default=0)
    policy_remarks: str | None = Field(default=None)
    medical_legibility: AuditMedicalLegibility = Field(default_factory=AuditMedicalLegibility)
    policy_violations: list[AuditPolicyViolation] = Field(default_factory=list)
    icd_codes: list[AuditIcdCode] = Field(default_factory=list)
    icd_validation: list[dict[str, Any]] = Field(default_factory=list)
    fwa_flags: list[str] = Field(default_factory=list)
    fwas: list[dict[str, Any]] = Field(default_factory=list)
    invoice_duplicate_fwa: dict[str, Any] = Field(default_factory=dict)
    patches: list[AuditPatch] = Field(default_factory=list)

    # Validation fields
    mathematical_consistency: bool | None = Field(default=None)
    all_duplicates_found: bool | None = Field(default=None)
    claim_amount_verified: bool | None = Field(default=None)
    medical_legibility_passed: bool | None = Field(default=None)
    policy_rules_checked: bool | None = Field(default=None)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# policy_extraction (ekincare) — superclaims schemas/ekincare.py.
# ---------------------------------------------------------------------------
class EkincarePolicyExtractionOutput(BaseModel):
    nme_items: list[str] = Field(default_factory=list)
    policy_rules: list[str] = Field(default_factory=list)
    extraction_ok: bool = False
    source: Literal["payload_text", "payload_json", "document", "fallback"] = "fallback"


# ---------------------------------------------------------------------------
# benefit_plan (ekincare) — superclaims schemas/ekincare.py.
# ---------------------------------------------------------------------------
class PlanApplicability(BaseModel):
    benefit_id: int | str | None = None
    benefit_name: str
    applicable: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = None


class BenefitItemAssignment(BaseModel):
    item_index: int | None = None
    bill_id: str | None = None
    item_s_no: int | str | None = None
    benefit_id: int | str | None = None
    benefit_name: str | None = None
    reason: str | None = None
    rationale: str | None = None


class BenefitPlanSelectionOutput(BaseModel):
    # Both arrays are required (no defaults) so json_schema structured output always emits each
    # key — kept verbatim from production where defaults caused models to drop item_assignments.
    plan_applicability: list[PlanApplicability]
    item_assignments: list[BenefitItemAssignment]

# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/ekincare.py
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


class EkincarePolicyExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nme_items: list[str]
    policy_rules: list[str]
    extraction_ok: bool
    source: Literal["payload_text", "payload_json", "document", "fallback"]


class PlanApplicability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benefit_id: int | str | None
    benefit_name: str
    applicable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None


class BenefitItemAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_index: SkipJsonSchema[int | None] = None
    bill_id: str | None
    item_s_no: int | str | None
    benefit_id: int | str | None
    benefit_name: str | None
    reason: SkipJsonSchema[str | None] = None
    rationale: SkipJsonSchema[str | None] = None


class BenefitPlanSelectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Both arrays are required (no defaults) so Gemini's json_schema structured output
    # always emits each key. With defaults they were absent from the schema's `required`
    # set, and the model silently dropped `item_assignments` entirely from its response.
    plan_applicability: list[PlanApplicability]
    item_assignments: list[BenefitItemAssignment]


class DeficiencyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["MATCHED", "RAISE_DEFICIENCY", "REJECTED", "NOT_APPLICABLE"]
    codes: list[str]
    messages: list[str]
    reason: str | None
    detail: dict[str, Any]


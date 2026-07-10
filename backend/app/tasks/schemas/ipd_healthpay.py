"""Structured outputs for the healthpay-ai@test-fhpl IPD task pack."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.tasks.schemas.ipd_document_segregator_reference import (
    DocumentSegregatorResponse as IpdDocumentSegregatorResponse,
)
from app.tasks.schemas.ipd_nme_reference import NMEAnalysisResponse
from app.tasks.schemas.opd_healthpay import (
    ConsolidatedBillsOutput as IpdConsolidatedBillsOutput,
)
from app.tasks.schemas.opd_healthpay import (
    ItemizedBillsOutput as IpdItemizedBillsOutput,
)
from app.tasks.schemas.opd_healthpay import (
    ItemsCategorisationOutput as IpdItemsCategorisationOutput,
)
from app.tasks.schemas.opd_superclaims import (
    BankDetailsOutput,
    IdentityDocumentOutput,
)
from app.tasks.schemas.opd_superclaims import (
    ClaimFormOutput as IpdClaimFormOutput,
)


class FlexibleOutput(BaseModel):
    model_config = ConfigDict(extra="allow")


class DischargeSummaryOutput(FlexibleOutput):
    claims_digitization_details: dict[str, Any] = Field(default_factory=dict)


class PatientSummaryData(FlexibleOutput):
    patient_details: dict[str, Any] = Field(default_factory=dict)
    hospitalization_details: dict[str, Any] = Field(default_factory=dict)
    clinical_details: dict[str, Any] = Field(default_factory=dict)
    past_history_details: dict[str, Any] = Field(default_factory=dict)


class AuditPatch(FlexibleOutput):
    type: str
    reason: str | None = None


class IpdAuditOutput(FlexibleOutput):
    analysis: dict[str, Any] = Field(default_factory=dict)
    patches: list[AuditPatch] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class ValidationScores(FlexibleOutput):
    bill_total: float = 0
    admissible_total: float = 0
    patient_summary_complete: bool = False


__all__ = [
    "BankDetailsOutput",
    "DischargeSummaryOutput",
    "IdentityDocumentOutput",
    "IpdAuditOutput",
    "IpdClaimFormOutput",
    "IpdConsolidatedBillsOutput",
    "IpdDocumentSegregatorResponse",
    "IpdItemizedBillsOutput",
    "IpdItemsCategorisationOutput",
    "NMEAnalysisResponse",
    "PatientSummaryData",
    "ValidationScores",
]

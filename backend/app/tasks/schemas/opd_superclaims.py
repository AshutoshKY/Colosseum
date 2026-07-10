"""Schemas for the OPD parity agents ported from superclaims-ai@test-ekincare-v2."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlexibleOutput(BaseModel):
    model_config = ConfigDict(extra="allow")


class ClaimFormOutput(FlexibleOutput):
    part_a: dict[str, Any] = Field(default_factory=dict)
    part_b: dict[str, Any] = Field(default_factory=dict)


class PrescriptionOutput(FlexibleOutput):
    claims_digitization_details: dict[str, Any] = Field(default_factory=dict)


class IdentityDocumentOutput(FlexibleOutput):
    identity_documents: list[dict[str, Any]] = Field(default_factory=list)


class BankDetailsOutput(FlexibleOutput):
    bank_details: dict[str, Any] = Field(default_factory=dict)


class IcdCodeCandidate(FlexibleOutput):
    code: str | None = None
    name: str | None = None
    diagnosis: str | None = None
    related_bill_ids: list[str] = Field(default_factory=list)


class ExtractIcdCodesOutput(FlexibleOutput):
    icd_codes: list[IcdCodeCandidate] = Field(default_factory=list)


class PatientSummaryOutput(FlexibleOutput):
    patient_summary: dict[str, Any] = Field(default_factory=dict)

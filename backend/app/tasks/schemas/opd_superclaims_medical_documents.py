# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/medical_documents.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LabReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_name: str | None
    report_date: str | None
    lab_name: str | None
    referring_doctor_name: str | None = Field(
        default=None,
        description=(
            "Name of the referring / consulting / ordering doctor printed on the report "
            "(e.g. 'Ref. By Dr. ...', 'Referred by'). Null if no doctor is named."
        ),
    )
    referring_doctor_registration: str | None = Field(
        default=None,
        description="Referring doctor's medical registration / council number if printed. Null if absent.",
    )
    tests: list[dict[str, str | None]]
    abnormal_findings: list[str]


class IdentityDocumentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pan_card_number: str | None
    aadhar_card_number: str | None


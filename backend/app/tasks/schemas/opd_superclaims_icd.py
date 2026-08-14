# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/icd.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IcdCodeCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | None = Field(..., description="ICD-10 code, for example J06.9.")
    name: str | None = Field(..., description="Official or best-known ICD-10 name.")
    diagnosis: str | None = Field(..., description="Clinical term or diagnosis supporting this code.")
    description: str | None = Field(..., description="Official ICD-10 description/name.")
    chapter: str | None = Field(..., description="ICD-10 chapter if known.")
    block: str | None = Field(..., description="ICD-10 block if known.")
    source: str | None = Field(..., description="Prescription evidence used to select this code.")
    type: Literal["primary", "secondary"] | None = Field(..., description="primary or secondary.")
    related_bill_ids: list[str] = Field(
        ...,
        description=(
            "Bill IDs of the bill items that this diagnosis directly supports or relates to. "
            "Empty list when no bill items are relevant or no bills are provided."
        ),
    )


class ExtractIcdCodesOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    icd_codes: list[IcdCodeCandidate] = Field(...)


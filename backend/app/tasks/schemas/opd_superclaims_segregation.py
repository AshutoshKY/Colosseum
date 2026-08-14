# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/segregation.py
from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType = Field(
        description=(
            "The type of document classified. There must be at most one entry per document type, "
            "except itemized_bill may appear at most twice (is_pharmacy_bill true and false)."
        ),
    )
    pages: str = Field(
        description=(
            "All comma-separated 1-based page numbers or ranges belonging to this document type in the entire PDF. "
            "Combine all separate occurrences into this single entry."
        ),
    )
    is_pharmacy_bill: bool | None = Field(
        default=None,
        description=(
            "Only for itemized_bill: true for standalone pharmacy/chemist bills, false for hospital/clinic "
            "itemized bills. Omit (null) for all other document types."
        ),
    )

    @model_validator(mode="after")
    def validate_pharmacy_flag(self) -> Self:
        if self.document_type != "itemized_bill" and self.is_pharmacy_bill is not None:
            raise ValueError("is_pharmacy_bill is only allowed for itemized_bill segments")
        return self


class RequiredDocumentCheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_name: str
    benefit_name: str | None
    benefit_id: int | str | None
    present: bool
    matched_segment: str | None


class RequiredDocumentsCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_present: bool
    results: list[RequiredDocumentCheckItem]


class DocumentSegregatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[DocumentSegment] = Field(
        description=(
            "List of unique document segments identified in the claims packet. "
            "There must be at most one segment for each document type, except itemized_bill may appear "
            "at most once per is_pharmacy_bill value (true and false)."
        ),
    )
    required_documents_check: RequiredDocumentsCheck | None

    @model_validator(mode="after")
    def validate_unique_segments(self) -> Self:
        seen: set[tuple[str, bool | None]] = set()
        for segment in self.segments:
            pharmacy_flag = segment.is_pharmacy_bill if segment.document_type == "itemized_bill" else None
            key = (segment.document_type, pharmacy_flag)
            if key in seen:
                raise ValueError(f"duplicate segment for document_type={segment.document_type!r}")
            seen.add(key)
        return self


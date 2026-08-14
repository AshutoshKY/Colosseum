# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/bank_identity.py
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AccountType(StrEnum):
    SAVINGS = "Savings"
    CURRENT = "Current"
    OTHER = "Other"


class BankDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ifsc_code: str | None
    bank_name: str | None
    bank_branch: str | None
    account_no: str | None
    account_holder_name: str | None
    account_type: AccountType | None


class BankDetailsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_details: BankDetails | None


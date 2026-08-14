# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/claim_form.py
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class ClaimFormPartA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_no: str | None = Field(description="Policy number of the insurance policy (max 30 characters).")
    full_name: str | None = Field(description="Full name of the patient actually receiving medical treatment.")
    age_years: float | None = Field(description="Age of the patient in years.")
    gender: Gender | None = Field(description="Gender of the patient.")
    address: str | None = Field(description="Address of the primary insured / claimant / policyholder.")
    city: str | None = Field(description="City of the primary insured.")
    pin_code: str | None = Field(description="PIN code of the primary insured.")
    phone_no: str | None = Field(description="Phone number of the primary insured.")
    state: str | None = Field(description="State of the primary insured.")
    email_id: str | None = Field(description="Email address of the primary insured.")
    diagnosis: str | None = Field(description="Diagnosis details written on the claim form.")
    date_of_admission: str | None = Field(description="Date of admission in YYYY-MM-DD format.")
    time_admission: str | None = Field(description="Time of admission in HH:MM format.")
    date_of_discharge: str | None = Field(description="Date of discharge in YYYY-MM-DD format.")
    time_discharge: str | None = Field(description="Time of discharge in HH:MM format.")
    pre_hospitalization_expenses: float | None = Field(description="Pre-hospitalization expenses claimed.")
    hospitalization_expenses: float | None = Field(description="Hospitalization expenses claimed.")
    post_hospitalization_expenses: float | None = Field(description="Post-hospitalization expenses claimed.")
    total: float | None = Field(description="Total claimed expenses.")


class ClaimFormPartB(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_of_treating_doctor: str | None = Field(description="Name of the treating physician / doctor.")
    registration_no_with_state_code: str | None = Field(description="Registration number of the treating doctor.")
    phone_no: str | None = Field(description="Phone number / contact number of the hospital / doctor.")
    name_of_the_patient: str | None = Field(description="Name of the patient as recorded on Part B.")


class ClaimFormDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_a: ClaimFormPartA | None = Field(description="Details extracted from Part A.")
    part_b: ClaimFormPartB | None = Field(description="Details extracted from Part B.")


class ClaimFormOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_form: ClaimFormDetails = Field(..., description="Structured claim form details.")


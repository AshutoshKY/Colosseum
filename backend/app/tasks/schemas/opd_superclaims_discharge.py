# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/discharge_summary.py
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TypeOfNatureOfTreatment(StrEnum):
    ALLOPATHY = "Allopathy"
    AYURVEDIC = "Ayurvedic"
    HOMEOPATHY = "Homeopathy"
    SIDDHA = "Siddha"
    UNNANI = "Unnani"
    YOGA = "Yoga"
    NATUROPATHY = "Naturopathy"


class NatureOfTreatment(StrEnum):
    ALLOPATHY = "Allopathy"
    AYUSH = "Ayush"


class AvailedAccommodation(StrEnum):
    GENERAL_WARD = "General Ward"
    GENERAL_WARD_AC = "General Ward A/C"
    ICU = "ICU"
    HDU = "HDU"
    HDU_ROOM = "HDU Room"
    SINGLE = "Single"
    SINGLE_AC = "Single A/C"
    PRIVATE = "Private"
    DELUXE = "Deluxe"
    SUITE = "Suite"
    SEMI_PRIVATE = "Semi Private"
    SEMI_DELUX = "Semi Delux"
    DAY_CARE = "Day Care"
    LABOR_ROOM = "Labor Room"
    POST_OP = "Post OP."
    CASUALTY = "Casuality"
    SHARING_DOUBLE = "Sharing - Double"
    SHARING_TRIPLE = "Sharing - Triple"
    SHARING_MULTIPLE = "Sharing - Multiple"
    SHARING_DOUBLE_AC = "Sharing - Double A/C"
    SHARING_TRIPLE_AC = "Sharing - Triple A/C"
    SHARING_MULTIPLE_AC = "Sharing - Multiple A/C"


class PatientCondition(StrEnum):
    RECOVERED = "Recovered"
    TRANSFERRED = "Transferred"
    NOT_ALIVE = "Not Alive"
    LAMA = "LAMA"


class ProbableLineOfTreatment(StrEnum):
    MEDICAL = "Medical"
    SURGICAL = "Surgical"


class TypeOfAnaesthesia(StrEnum):
    GENERAL = "General"
    SPINAL = "Spinal"
    EPIDURAL = "Epidural"
    LOCAL = "Local"
    REGIONAL = "Regional"


class RouteOfDrugAdministration(StrEnum):
    ORAL = "Oral"
    IV = "IV"
    IM = "IM"
    SC = "SC"
    TOPICAL = "Topical"
    INHALATION = "Inhalation"


class AdmissionType(StrEnum):
    PLANNED = "Planned"
    EMERGENCY = "Emergency"


class ClaimsDigitizationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_of_treating_doctor: str | None = Field(description="Name of treating physician.")
    treating_doctor_registration: str | None = Field(description="Medical registration number.")
    type_of_nature_of_treatment: TypeOfNatureOfTreatment | None
    nature_of_treatment: NatureOfTreatment | None
    availed_accommodation: AvailedAccommodation | None
    date_of_admission: str | None
    time_of_admission: str | None
    date_of_discharge: str | None
    time_of_discharge: str | None
    diagnosis: str | None
    presenting_complaint: str | None
    patient_condition: PatientCondition | None
    ip_no: str | None
    room_days: float | None
    icu_days: float | None
    duration_of_ailment: str | None
    temperature_f: str | None
    cvs: str | None
    pa: str | None
    probable_line_of_treatment: ProbableLineOfTreatment | None
    treatment_details: str | None
    type_of_anaesthesia: TypeOfAnaesthesia | None
    route_of_drug_administration: RouteOfDrugAdministration | None
    admission_type: AdmissionType | None
    cancer: str | None
    copd: str | None
    medical_past_history: str | None
    history_of_past_illness: str | None
    is_maternity: bool | None
    gplad: str | None
    lmp: str | None
    date_of_delivery: str | None
    accident_case: bool | None
    is_death_case: bool | None
    date_of_death: str | None
    time_of_death: str | None


class DischargeSummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims_digitization_details: ClaimsDigitizationDetails = Field(..., description="Discharge summary details.")


class PrescribedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    medicine_name: str = Field(..., description="Medicine name exactly as written on the prescription.")
    dosage: str | None = Field(..., description="Dose/strength, for example '500 mg', if present.")
    frequency: str | None = Field(..., description="How often the medicine should be taken, if present.")
    duration: str | None = Field(..., description="Treatment duration, if present.")
    quantity: int | None = Field(..., description="Prescribed quantity, if present.")
    route: str | None = Field(..., description="Route of administration, if present.")
    instructions: str | None = Field(..., description="Additional administration instructions, if present.")


class PrescriptionClaimsDigitizationDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patient_name: str | None = Field(
        ...,
        description="Full name of the patient receiving treatment, exactly as printed on the prescription.",
    )
    name_of_treating_doctor: str | None = Field(...)
    treating_doctor_qualification: str | None = Field(
        ...,
        description=(
            "Doctor qualifications and specialisation exactly as printed, "
            "e.g. 'M.B.B.S, D.G.O Consultant Obstetrician'."
        ),
    )
    treating_doctor_mobile: str | None = Field(...)
    treating_doctor_registration: str | None = Field(
        ...,
        description="Doctor's medical registration / council number, exactly as printed.",
    )
    diagnosis: str | None = Field(...)
    presenting_complaint: str | None = Field(...)
    claimed_amount: float | None = Field(...)
    temperature_f: str | None = Field(...)
    hospital_name: str | None = Field(...)
    hospital_address: str | None = Field(...)
    hospital_city: str | None = Field(...)
    hospital_state: str | None = Field(...)
    hospital_pincode: str | None = Field(...)
    hospital_phone_number: str | None = Field(...)
    hospital_gst: str | None = Field(...)
    patient_age: int | None = Field(...)
    prescription_date: str | None = Field(..., description="Prescription date in YYYY/MM/DD format, if present.")
    prescribed_items: list[PrescribedItem] = Field(..., description="Medicines prescribed in the document.")


class PrescriptionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims_digitization_details: PrescriptionClaimsDigitizationDetails = Field(..., description="Prescription details.")


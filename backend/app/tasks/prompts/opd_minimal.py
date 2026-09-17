"""Small OPD prompts for testing how models perform with little guidance."""

from __future__ import annotations

MINIMAL_OPD_PROMPTS: dict[str, tuple[str, str]] = {
    "segregation": (
        """Classify every 1-based PDF page exactly once as claim_forms, cheque_or_bank_details,
identity_document, itemized_bill, consolidated_bill, discharge_summary, prescription,
investigation_report, cash_receipt, or other. Combine each type into one ascending page-range
string. A named medicine/service/test plus price is itemized_bill; category totals only are
consolidated_bill; a payment total without named items is cash_receipt; clinical results are
investigation_report. Account number plus IFSC is cheque_or_bank_details even on an identity-style
bank card; identity_document means government ID. Use other for blank or irrelevant pages. Set
is_pharmacy_bill only for itemized_bill and split pharmacy/non-pharmacy when both exist. Set
required_documents_check to null unless requirements are supplied; then report each requirement.""",
        "Classify the attached claim packet.",
    ),
    "policy_extraction": (
        """Extract only explicit OPD non-medical items and adjudication rules: inclusions,
exclusions, caps, conditions, and required documents. Do not infer rules. Use empty arrays when
absent. Set source to payload_json for JSON, payload_text for text, document for document content,
or fallback when unusable; extraction_ok is false only when nothing reliable can be extracted.""",
        "Policy input:\n{policy_context}",
    ),
    "claim_form": (
        """Extract visible claim-form fields only; use null when absent. Part A patient identity
fields describe the treated person, while Part A contact/address fields describe the primary
insured. Part B describes the treating doctor. Normalize dates as YYYY-MM-DD, times as HH:MM, and
money as numbers without symbols or commas.""",
        "Extract the attached claim form.",
    ),
    "identity_document": (
        "Extract visible PAN (10 uppercase alphanumerics) and Aadhaar (12 digits, no separators). Use null when absent.",
        "Extract the attached identity document.",
    ),
    "prescription": (
        """Extract only visible prescription facts; use null when absent. Keep patient and doctor
identity distinct. Capture confident diagnosis/complaints, provider details, date as YYYY/MM/DD,
and every prescribed medicine with dosage, frequency, duration, quantity, route, and instructions.
Do not invent illegible handwriting.""",
        "Extract the attached prescription.",
    ),
    "cheque_bank": (
        """Extract the refund account visible on the cheque or bank document; use null when absent.
Ignore CANCELLED/payee text, signatures, CIF/customer ID, cheque number, MICR, UTR, phone, PAN, and
Aadhaar. Preserve account-number leading zeros, normalize IFSC to 11 uppercase characters, and map
SB/Savings to Savings and CA/Current to Current. Default account_type to Savings only.""",
        "Extract the attached bank document.",
    ),
    "itemized_bills": (
        """Extract each billed medicine, service, or charge as a separate item. Copy patient and
facility details only from the bill and use null when absent. final_amount is the gross printed line
total before discount, or unit_price * quantity only when no line total exists. net_amount is the
post-discount item amount only when printed. Header total_discount and net_amount come from the bill
summary. Preserve negative returns and normalize bill_date as YYYY-MM-DD.""",
        "Extract the attached itemized bill pages.",
    ),
    "consolidated_bills": (
        """Extract each department or summary charge as a separate item. Copy patient and facility
details only from the bill and use null when absent. final_amount is the gross printed line total
before discount, or unit_price * quantity only when no line total exists. net_amount is the
post-discount item amount only when printed. Header total_discount and net_amount come from the bill
summary. Preserve negative returns and normalize bill_date as YYYY-MM-DD.""",
        "Extract the attached consolidated bill pages.",
    ),
    "items_categorisation": (
        """Categorize every input item exactly once, preserving bill_id and s.no. Use only these
category names: ICU Charges; Room Rent; Nursing Charges; DMO/RMO Charges; Surgeon/Physician;
Assistant Surgeon; Anaesthetist; Consultation; Medicines Supplied By Hospital; Medicines From Shop;
Radiation Therapy; Blood/Blood components; Labs/Bio/Micro/Pathology/Immuno/Histo/Cyto chemistry;
Imageology; F & B; File / Admission; Ambulance; Registration; Implants; OT Charges; OT Consumables;
Anaesthesia gas; Instrument Charges; Procedures; Oxygen; Nebulizor; Ventilator; Pulse oxy;
Physiotherapy; Casualty / emergency chrgs; Donar Charges; Dental; Vision/Optical; Others. Match by
meaning; distinguish hospital pharmacy from an outside shop using facility name. Use Others when
uncertain.""",
        "Bills:\n{bills_json}",
    ),
    "nme_analysis": (
        """Return only clearly non-medical bill items, one entry per input item, using its s.no.,
item_name, and final_amount. Typical NME: administrative/file/document charges, toiletries and
personal-comfort items, guest food, laundry/housekeeping/convenience charges, unprescribed cosmetic
items, separately billed disposable consumables included in another service, and external home-use
devices. Do not flag doctor/RMO/DMO fees, room rent, clinical packages, monitoring, dressing service,
ambulance, or prescribed medicines. State the specific deduction reason. Add policy_violations only
for explicit claim-specific rules present in the input; otherwise return an empty list.""",
        "Bills:\n{bills_json}",
    ),
    "extract_icd_codes": (
        """Select ICD-10 candidates from documented clinical evidence. Prefer diagnosis as primary;
use symptoms when no diagnosis exists and medicines only as support. Do not infer a disease from a
drug alone. Return an empty list when evidence is insufficient. Link only exact bill_id values from
supplied bill_items that the code directly supports; otherwise use an empty related_bill_ids list.
Use null for unknown metadata.""",
        "Context:\n{context_json}",
    ),
    "benefit_plan": (
        """Return one plan_applicability row per input benefit and one item_assignment per bill item,
using exact input IDs and names. Match consultation, medicine, lab, imaging, dental, physiotherapy,
vision, and procedure categories to the corresponding plan. A specialty plan captures its related
episode only when clinical_context supports that specialty; otherwise use the item's category.
Administrative items follow the dominant clinical service on their bill. An assigned plan must be
applicable; mark unmatched plans not applicable. Never invent a plan; use null and Unclassified when
none fits.""",
        "Input JSON (bills, benefits, policy_context, clinical_context):\n{benefit_context}",
    ),
    "audit": (
        """Audit bill pages against extracted bill data. Find missing or duplicate bills/items and
incorrect header, item, or total values. Prefer itemized
detail over a duplicate consolidated summary and keep legitimate negative returns. Ignore differences
below Rs 1 or 0.5%. Emit only evidence-backed patches with page/invoice/calculation when available;
use the matching patch type and null for inapplicable fields.""",
        """Compare the attached bill pages with this extracted data.
Calculated total: {{CALCULATED_TOTAL}}
Extracted bills: {{JSON_OUTPUT}}""",
    ),
}

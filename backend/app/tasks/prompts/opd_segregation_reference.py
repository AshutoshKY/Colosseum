# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/prompts/segregation.py
from __future__ import annotations

DOCS_SEGREGATOR_SYSTEM_PROMPT = """\
You are an expert medical claims document segregator.
Analyze the pages of a medical claim packet and classify them into the document types below.

<document_types>
- claim_forms: Insurance claim form (boxed fields, "Claim Form Part A/B", policyholder info, signatures).
- discharge_summary: Clinical report at end of hospital stay (admission/discharge dates, diagnosis, treatment, follow-up).
- itemized_bill: Bill with individual line items OR a single named service + amount.
- consolidated_bill: Summary bill showing only department/category totals (Room Rent, OT, Nursing, Pharmacy) with no per-item detail.
- prescription: Doctor's prescription slip (Rx notation, medication list with dosage/frequency, doctor stamp).
- investigation_report: Diagnostic results with values and reference ranges (blood work, ECG, imaging). If the document lists test prices → itemized_bill instead.
- cheque_or_bank_details: Cancelled cheque, bank passbook, bank statement, bank letter, NEFT/RTGS mandate form,
  bank account detail screenshot/card, or any document showing account number + IFSC. Bank-issued kiosk/customer
  identity cards (e.g. "SBI - Kiosk Banking Duplicate Identity Card") belong here when they show bank settlement
  fields like CIF Number, Account Number, IFSC Code, and customer name — do NOT classify these as identity_document
  just because the title contains "Identity Card" or a photo is present. If a page has both identity-style
  layout/photo and bank settlement fields, classify it as cheque_or_bank_details when account number and IFSC
  are present.
- identity_document: Government ID with photograph (Aadhaar, PAN, Voter ID, Driving License, Passport).
  Exclude bank-issued account/customer cards that primarily provide account number, IFSC, CIF, bank name, and
  account-holder name; those belong to cheque_or_bank_details.
- cash_receipt: Payment acknowledgment with a total amount only — no line-item breakdown. Covers advance receipts, deposit receipts, UPI/digital payment slips, credit notes.
- other: Consent forms, referral letters, blank/illegible pages, marketing material, generic T&C.
</document_types>

<bill_decision_tree>
For any financial document, follow these steps in order:

STEP 1: Does it show only department/category totals with no granular line items?
  Look for: Room Rent, Dr. Round Charges, OT Charges, Nursing, Admission fees — as lump-sum or per-day amounts.
  YES → consolidated_bill

STEP 2: Does it name a specific service, procedure, or investigation with a price?
  Look for: medicines, named procedures, lab/pathology tests (e.g. CBC, X-Ray, CBL), or any named service + amount.
  A single named test on a receipt slip still qualifies — classify as itemized_bill.
  YES → itemized_bill (regardless of title or slip format)

STEP 3: Is it a total-amount-only payment acknowledgment with NO named service or item?
  Look for: advance receipts, deposit receipts, UPI/digital payment slips, credit notes — just a total amount paid.
  GUARD: If the document names any specific service, test, or medicine, it must be classified in STEP 2, not here.
  YES → cash_receipt

STEP 4: → other
</bill_decision_tree>

<back_side_policy>
Group a back-side page with its front document ONLY IF it continues form fields, signatures, or information
essential for claims processing.
Classify as "other" if it contains generic T&C, marketing, blank content, or anything not needed for claims.
When in doubt, SEPARATE.
</back_side_policy>

<rules>
- One segment per document_type. Combine all pages (consecutive or non-consecutive) into one compact page
  string (e.g. '1-3,7,15-18'). Keep pages in ascending order.
- Use PDF sequence numbers (1-based), not printed page numbers.
- Each page belongs to exactly one document type. No overlaps.
</rules>
"""


def build_ekincare_opd_document_check_prompt(benefits: list[dict[str, object]]) -> str:
    required_docs: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for benefit in benefits:
        benefit_id = benefit.get("benefit_id")
        benefit_name = str(benefit.get("benefit_name") or benefit.get("name") or "")
        requirements = benefit.get("required_documents")
        if not isinstance(requirements, list):
            continue
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            requirement_type = str(requirement.get("requirement_type") or "required").lower()
            if requirement_type not in {"required", "conditional"}:
                continue
            document_name = str(requirement.get("document_name") or "").strip()
            if not document_name:
                continue
            key = (str(benefit_id), document_name.lower())
            if key in seen:
                continue
            seen.add(key)
            required_docs.append(
                {
                    "document_name": document_name,
                    "benefit_name": benefit_name,
                    "benefit_id": benefit_id,
                    "requirement_type": requirement_type,
                }
            )

    if not required_docs:
        return ""

    lines = "\n".join(
        f'- "{item["document_name"]}" ({item["requirement_type"]}) '
        f'for benefit "{item["benefit_name"]}", id {item["benefit_id"]}'
        for item in required_docs
    )
    return f"""

<ekincare_opd_document_check>
Additional Ekincare OPD task:
After classifying document pages, verify whether these required or conditional benefit documents are present:
{lines}

Semantic matching rules:
- Doctor prescription, Doctor Rx -> prescription
- Consultation receipt, OPD bill, doctor visit receipt -> itemized_bill that is not clearly a pharmacy-only bill
- Pharmacy bill, medicine invoice, drug store bill -> itemized_bill with pharmacy evidence
- Lab report, diagnostic report, pathology report -> investigation_report
- Discharge summary -> discharge_summary

Return required_documents_check with one result per listed document and benefit.
</ekincare_opd_document_check>
"""


# Source: healthpay-ai@test-fhpl healthpay/backend/app/lang_graph/prompts/audit.py
"""Enhanced audit prompt for medical bill verification and discrepancy analysis."""

# ---------------------------------------------------------------------------
# Canonical item categories (mirrors the list in bills.py ITEMS_CATEGORISATION_SYSTEM_PROMPT).
# ---------------------------------------------------------------------------
_VALID_ITEM_CATEGORIES: list[str] = [
    "ICU Charges",
    "Room Rent",
    "Nursing Charges",
    "DMO/RMO Charges",
    "Surgeon/Physician",
    "Assistant Surgeon",
    "Anaesthetist",
    "Consultation",
    "Medicines Supplied By Hospital",
    "Medicines From Shop",
    "Radiation Therapy",
    "Blood/Blood components",
    "Labs/Bio/Micro/Pathology/Immuno/Histo/Cyto chemistry",
    "Imageology",
    "F & B",
    "Others",
    "File / Admission",
    "Ambulance",
    "Registration",
    "Implants",
    "OT Charges",
    "OT Consumables",
    "Anaesthesia gas",
    "Instrument Charges",
    "Procedures",
    "Oxygen",
    "Nebulizor",
    "Ventilator",
    "Pulse oxy",
    "Physiotherapy",
    "Casualty / emergency chrgs",
    "Donar Charges",
]

# Formatted string injected into prompts so the LLM must choose from this list.
_CATEGORY_LIST_STR = ", ".join(f'"{c}"' for c in _VALID_ITEM_CATEGORIES)

# ---------------------------------------------------------------------------
# CORE BLOCKS (Common across all audit types)
# ---------------------------------------------------------------------------

CORE_PRINCIPLES = """Core Principles:
- STRICT EVIDENCE: Only use facts visible in documents
- DECIMAL TOLERANCE: Ignore differences < ₹1.00 or < 0.5% (do NOT patch minor rounding differences)
- KEEP BREAKUP BILLS: When duplicates exist between consolidated and itemized bills, delete from consolidated bills, keep itemized/breakup bills
- NO ASSUMPTIONS: Do not infer missing data"""

CORE_CONTEXT_HEADER = """<context>
Claimed Amount: {{CLAIMED_AMOUNT}}
Calculated Total: {{CALCULATED_TOTAL}}

The JSON comes from a multi-stage extraction pipeline:
1. Pages are classified as "itemized_bill" or "consolidated_bill" during segregation
2. Itemized bills = detailed line items (individual medicines, services like "INJ. ARTIVIL", "Tab Paracetamol 650mg")
3. Consolidated bills = category totals (e.g., "MEDICINE: ₹3668.80", "PHARMACY CHARGES") without item-level details
4. Both are merged into a single bills array for analysis

Extracted JSON:
{{JSON_OUTPUT}}

Patient Summary Fields:
{{PATIENT_SUMMARY_FIELDS}}"""

CORE_PATIENT_VERIFICATION = """**Patient Summary Verification (CRITICAL):**
The flat keys above come from 4 sections (patient_details, hospitalization_details, clinical_details, past_history_details). 
You MUST critically analyze EACH of these fields against the PDF evidence.
- If a value is incorrect (e.g., wrong name, wrong date, wrong number), create an `EDIT_PATIENT_SUMMARY` patch with the correct value.
- Use the EXACT key name provided in the list above.
- SOURCE HIERARCHY: Prioritize signed claim forms for identity and primary insured/claimant details. Do NOT use Aadhaar cards or other identity documents to "correct" information already present in a signed claim form.
- **CLAIM FORM PERSON RESOLUTION (CRITICAL)**:
  - Hospitalized Person/Patient scoped fields: `patient_name`, `patient_age`, `patient_gender`, `patient_pan_no`, and `patient_aadhar_no`.
  - Primary Insured/Claimant/Policyholder scoped fields: `patient_address_1`, `patient_address_2`, `patient_state`, `patient_district`, `patient_city`, `patient_pincode`, `patient_STD_Code`, `relative_mobile`, `patient_mobile`, `patient_email`, `patient_occupation`, `patient_policy_no`, and bank fields.
  - If the Claim Form shows a "Primary Insured" and a different "Hospitalized Person/Patient", correct name/age/gender and patient ID fields to the Hospitalized Person. Do NOT rewrite address, mobile, email, occupation, policy, or bank fields to the Hospitalized Person.
  - If you patch a Primary Insured scoped field, the reason MUST explicitly cite Primary Insured, Claimant, or Policyholder evidence.
- **IDENTITY DOCUMENT MATCHING**: Before using any PAN card, Aadhaar card, or identity document for verification, match it to the owner expected for the target field.
  - PAN/Aadhaar fields are mandatory Patient-owned fields. Only use IDs that explicitly match the Hospitalized Person/Patient.
  - If `patient_pan_no` or `patient_aadhar_no` belongs to the Primary Insured/Claimant/Policyholder or any other third party, and no matching patient-owned ID is present in the PDF, generate an `EDIT_PATIENT_SUMMARY` patch setting that ID field to an empty string `""`.

**Bank Details Source Restriction (MANDATORY):**
- Bank fields are: `patient_bank_account_no`, `patient_bank_name`, `patient_bank_branch_name`, `patient_bank_account_type`, `patient_bank_ifsc_code`.
- Treat cancelled cheque / cancelled check and bank statement pages as the ONLY valid evidence sources for bank fields.
- If bank details appear in claim forms or any other non-bank document, do NOT treat them as authoritative for correction.
- Do NOT generate `EDIT_PATIENT_SUMMARY` patches for bank fields unless supported by cancelled cheque/check or bank statement evidence."""

CORE_DUPLICATE_DETECTION = """<duplicate_detection>
**Primary Goal**: Identify consolidated summary items that duplicate itemized breakdowns. ALWAYS keep itemized/breakup bills and delete from consolidated bills.

**Step 1: Handle Returns (Pre-Analysis)**
- Positive charge + matching negative charge (same item, same date) = legitimate reversal, NOT duplicates
- Exclude charge/credit pairs from duplicate analysis entirely

**Step 2: Intra-Bill Aggregation (Most Common - CRITICAL)**
This detects when a consolidated bill has a summary line that duplicates detailed items in an itemized bill.

Condition:
- Consolidated bill has an item with generic name (e.g., "MEDICINE", "PHARMACY", "DRUG CHARGES") with a Vch No. and final_amount
- Itemized bill has detailed items (specific drug names like "INJ. ARTIVIL", "INJ. MVI") with the SAME Vch No.
- Sum of itemized items with that Vch No. equals the consolidated item amount (within tolerance)

Action: Use DELETE_ITEM to remove the consolidated summary line (keep the detailed itemized items)
Reason: "intra_bill_aggregation"

**Step 3: Cross-Bill Aggregation**
Use when Vch No. matching doesn't apply.

Condition:
- Consolidated bill has item like "PHARMACY CHARGES", "OUT SIDE MEDICINE", or "Total Pharmacy"
- Separate itemized pharmacy bills exist from the same bill_date
- Sum of itemized bill amounts equals the consolidated item amount (within tolerance)

Action: Use DELETE_ITEM to remove the consolidated summary line
Reason: "cross_bill_aggregation"

**Step 4: False Positive Prevention**
DO NOT flag as duplicates:
- Items from bills with different bill_date (daily charges like nursing, RMO fees, gloves are legitimate)
- Items with different Vch No. (separate transactions)
- Charge/credit pairs (returns are legitimate)

**Indicators of Consolidated Summary Items (DELETE these, not the detailed ones):**
- Generic names: "MEDICINE", "PHARMACY", "DRUG CHARGES", "TOTAL MEDICINES", "OUT SIDE MEDICINE"
- Round numbers that match sum of itemized items
- Single line representing multiple detailed items elsewhere
</duplicate_detection>"""

CORE_MISSING_BILL_DETECTION = f"""<missing_bill_detection>
**CRITICAL**: Scan the PDF for bills that may have been MISSED during extraction.

Bills can be missed due to:
- Misclassification during segmentation (e.g., classified as "cash_receipt" or "other" instead of "itemized_bill")
- OCR failures on certain pages
- Multi-page bills where some pages were skipped
- External pharmacy bills not captured

**How to Detect Missing Bills:**
1. Look for invoice numbers in the PDF that don't appear in the extracted JSON
2. Check if the claimed amount significantly exceeds the total of extracted bills (may indicate missing bills)
3. Look for references to bills in discharge summaries or claim forms that aren't in the extraction. IMPORTANT: Use these only as evidence to find the ACTUAL bill pages; do NOT extract line items from summary tables within a claim form.
4. Scan pages classified as "cash_receipt" or "other" - they may contain itemized bills

**When You Find a Missing Bill:**
- Use ADD_BILL patch with complete bill structure
- Extract all visible line items from the PDF
- Include invoice_number, bill_date, facility_details
- Cite the page number where the bill was found
- **CATEGORY CONSTRAINT**: For every item's `category` field you MUST choose ONLY from this fixed list — do NOT invent or infer other values:
  {_CATEGORY_LIST_STR}

**Important:**
- Only add bills with clear evidence in the PDF
- Do NOT add bills that are already present (check invoice numbers)
- If a bill is partially extracted, use ADD_ITEM to add missing items instead
- **UPI / DIGITAL PAYMENT SCREENSHOTS ARE NOT VALID BILLS (NON-OPD)**: Do NOT create ADD_BILL patches for PhonePe, GPay, Paytm, BHIM, or any other UPI/digital payment confirmation screenshots. These are payment receipts, not medical bills — they do not constitute evidence of a claimable expense in non-OPD claims. Ignore them entirely when scanning for missing bills.
</missing_bill_detection>"""

CORE_DECIMAL_TOLERANCE = """<decimal_tolerance>
DO NOT generate patches for minor differences caused by rounding or OCR precision issues.

Tolerance Rules:
- Absolute: < ₹1.00 difference → NO PATCH
- Percentage: < 0.5% difference → NO PATCH

Examples - IGNORE (no patch needed):
- 3668.80 vs 3668.81 (₹0.01 difference)
- 125606.00 vs 125606.50 (₹0.50 difference)
- 10000.00 vs 10000.45 (0.0045% difference)

Examples - PATCH (significant errors):
- 4500 vs 45000 (10x difference - OCR decimal error)
- 25969.99 vs 125606 (significant mismatch)
- 8000 vs 80000 (10x difference)
</decimal_tolerance>"""

CORE_EXAMPLES = """**Example 1: Consolidated vs Itemized Duplicate (Most Common Case)**

INPUT:
- Bill 1 (consolidated hospital bill): has line "MEDICINE" with final_amount: 3668.80, Vch No: 7674036
- Bill 2 (itemized pharmacy bill): has 15 drug items (INJ. ARTIVIL ₹200, INJ. MVI ₹150, etc.) with same Vch No: 7674036, sum = 3668.80

ANALYSIS:
"The 'MEDICINE' line in Bill 1 is a consolidated summary of the 15 detailed drug items in Bill 2. Both share Vch No 7674036 and the amounts match. Keep the detailed breakdown, remove the summary."

OUTPUT:
{
  "type": "DELETE_ITEM",
  "bill_id": "bill_1_id",
  "item_s_no": 5,
  "reason": "Consolidated 'MEDICINE' line (Vch No 7674036) duplicates 15 itemized drugs in pharmacy bill totaling ₹3668.80. Keeping detailed breakdown.",
  "impact": "Reduces total by ₹3668.80"
}

**Example 2: Decimal Tolerance - No Patch Needed**

INPUT:
Bill net_amount: 125606.50
Sum of line items: 125606.00

ANALYSIS:
"Difference of ₹0.50 is within decimal tolerance (< ₹1.00). Likely rounding. No patch needed."

OUTPUT:
No patch generated.

**Example 3: Significant Calculation Error - Patch Required**

INPUT:
Bill net_amount: 25969.99
Sum of 156 line items: 125606.00

ANALYSIS:
"Difference of ₹99,636.01 is significant (not within tolerance). The net_amount appears to be an OCR error."

OUTPUT:
{
  "type": "EDIT_BILL_DETAILS",
  "bill_id": "abc123",
  "bill_invoice_number": "BL378455",
  "key": "net_amount",
  "old_value": 25969.99,
  "new_value": 125606.00,
  "reason": "Sum of 156 items = ₹125,606. Original value ₹25,969.99 is OCR error (likely missing digit).",
  "calculation": "Sum of all item.final_amount = 125606.00",
  "impact": "Increases total by ₹99,636.01"
}

**Example 4: Cross-Bill Aggregation Duplicate**

INPUT:
- Consolidated bill: has line "OUT SIDE MEDICINE" with final_amount: 5500.00
- Separate pharmacy bill from same date: invoice 12345, net_amount: 5500.00 with detailed drugs

ANALYSIS:
"The 'OUT SIDE MEDICINE' line is a summary of the external pharmacy bill. Amounts match exactly."

OUTPUT:
{
  "type": "DELETE_ITEM",
  "bill_id": "consolidated_bill_id",
  "item_s_no": 12,
  "reason": "Consolidated 'OUT SIDE MEDICINE' (₹5500) duplicates external pharmacy bill (Invoice 12345) with matching amount. Keeping detailed bill.",
  "impact": "Reduces total by ₹5500.00"
}

**Example 5: Duplicate Line Item Within Same Bill**

INPUT:
Bill abc123 shows "ECG" twice in extraction (s_no 6 and s_no 7)
PDF page 19 shows only one "ECG" entry

ANALYSIS:
"OCR extracted the same line item twice."

OUTPUT:
{
  "type": "DELETE_ITEM",
  "bill_id": "abc123",
  "item_s_no": 7,
  "reason": "Duplicate line item - ECG appears twice in extraction but only once on page 19",
  "page_reference": "19",
  "impact": "Reduces bill total by ₹500"
}

**Example 6: True Bill Duplicate (Same Invoice)**

INPUT:
- Bill 1: Invoice BL378455, 156 items, net_amount: 125606
- Bill 2: Invoice BL378455, 5 items (subset of Bill 1), net_amount: 828.26

ANALYSIS:
"Bill 2 is a partial extraction of Bill 1 - same invoice number, items are subset."

OUTPUT:
{
  "type": "DELETE_BILL",
  "bill_id": "bill_2_id",
  "bill_invoice_number": "BL378455",
  "bill_net_amount": 828.26,
  "reason": "Duplicate extraction - same invoice BL378455, items are subset of master bill",
  "impact": "Reduces total by ₹828.26"
}

**Example 7: Missing Bill Found in PDF**

INPUT:
- Extracted JSON has 3 bills totaling ₹85,000
- Claimed amount: ₹97,500 (discrepancy of ₹12,500)
- PDF page 45 shows an external pharmacy bill (Invoice PH-2024-789) with ₹12,500 not in extraction

ANALYSIS:
"Found missing pharmacy bill on page 45. Invoice PH-2024-789 dated 2024-01-18 with net_amount ₹12,500. This was likely misclassified as 'cash_receipt' during segmentation. Adding to extraction."

OUTPUT:
{
  "type": "ADD_BILL",
  "bill_data": {
    "bill": {
      "invoice_number": "PH-2024-789",
      "bill_date": "2024-01-18",
      "net_amount": 12500.00,
      "facility_details": {"name": "City Pharmacy"}
    },
    "items": [
      {"s_no": 1, "item_name": "Tab Augmentin 625mg", "final_amount": 450.00, "category": "Medicines From Shop"},
      {"s_no": 2, "item_name": "Tab Pantoprazole 40mg", "final_amount": 120.00, "category": "Medicines From Shop"},
      {"s_no": 3, "item_name": "Syrup Ascoril LS", "final_amount": 180.00, "category": "Medicines From Shop"},
      {"s_no": 4, "item_name": "Other medicines (8 items)", "final_amount": 11750.00, "category": "Medicines From Shop"}
    ]
  },
  "reason": "Missing pharmacy bill found on page 45. Invoice PH-2024-789 was not extracted (likely misclassified during segmentation). Explains ₹12,500 discrepancy.",
  "page_reference": "45",
  "impact": "Adds ₹12,500 - resolves discrepancy with claimed amount"
}

**Example 8: Patient Identity Correction With ID Eviction**

INPUT:
- Patient Summary: { "patient_name": "John Doe", "patient_aadhar_no": "1234-5678-9012" }
- Claim Form: Shows "Primary Insured: John Doe" and "Insured Person Hospitalized: Jane Doe (Daughter)"
- PDF Page 5: Aadhaar card for "John Doe"

ANALYSIS:
"The claim form indicates the patient is Jane Doe, but the summary currently has John Doe (the primary insured). I must correct the patient details. Also, the Aadhaar number in the summary belongs to John Doe, not the patient Jane Doe. Since Jane's Aadhaar is not in the PDF, I must clear the field."

OUTPUT:
[
  {
    "type": "EDIT_PATIENT_SUMMARY",
    "key": "patient_name",
    "old_value": "John Doe",
    "new_value": "Jane Doe",
    "reason": "Claim form shows Jane Doe is the hospitalized patient; John Doe is the primary insured."
  },
  {
    "type": "EDIT_PATIENT_SUMMARY",
    "key": "patient_aadhar_no",
    "old_value": "1234-5678-9012",
    "new_value": "",
    "reason": "Aadhaar 1234-5678-9012 belongs to John Doe (Primary Insured). Patient Jane Doe's ID is not present in PDF. Clearing incorrect ID.",
    "page_reference": "5"
  }
]"""

CORE_FOOTER_IMPORTANT = """<important>
- SCAN PDF FOR MISSING BILLS: Check all pages for bills not in extraction (especially pages classified as receipts/other)
- ALWAYS keep itemized/breakup bills with detailed item names (drugs, services)
- ONLY delete items from consolidated bills when duplicates exist with itemized bills
- Use DELETE_BILL only for true duplicates (same invoice, identical or subset items)
- DO NOT patch decimal differences within tolerance (< ₹1.00 or < 0.5%)
- Every patch must cite evidence (page numbers, calculations, Vch No. matching)
- BANK DETAILS SOURCE CONTROL: Bank detail edits are allowed only from cancelled cheque/check or bank statement evidence; never patch bank fields using claim form or other document types
- **PATIENT VS PRIMARY INSURED BOUNDARY**: `patient_name`, `patient_age`, `patient_gender`, `patient_pan_no`, and `patient_aadhar_no` must belong to the Hospitalized Person/Patient. Address, mobile, email, occupation, policy, and bank fields should remain Primary Insured/Claimant scoped.
- If claimed_amount is 0, only update it if explicit amount found in PDF
- If claimed amount exceeds extracted total significantly, actively search for missing bills
- **DO NOT add UPI/PhonePe/GPay/Paytm payment screenshots as ADD_BILL patches** — these are payment receipts, not claimable medical bills. They are only valid evidence in OPD claims.
- **DO NOT generate EDIT patches where `old_value` and `new_value` are identical** — if the current value is already correct, emit no patch at all. A patch that changes nothing is misleading and should be omitted.
</important>

Return ONLY valid JSON matching the output_schema."""

# ---------------------------------------------------------------------------
# OPD BLOCKS
# ---------------------------------------------------------------------------

OPD_MEDICAL_LEGIBILITY = """<medical_legibility_opd>
**CRITICAL OPD VALIDATION**: For OPD claims, perform comprehensive medical legibility checks.

**Step 1: Prescription-Bill Correlation**
Verify that billed items align with prescription:
- Medicines in pharmacy bills should match prescription (drug names, dosage forms)
- Lab tests in diagnostic bills should be justified by diagnosis or symptoms
- Procedures/services should correlate with chief complaint

**Step 2: Diagnosis-Treatment Consistency**
Check if treatments make medical sense for the diagnosis:
- Antibiotics: Should correlate with infectious/bacterial diagnosis
- Anti-inflammatory drugs: Should relate to inflammation-related complaints
- Specific investigations: Should be relevant to differential diagnosis

**Step 3: Lab Report-Diagnosis Alignment**
Verify investigation reports support the clinical picture:
- Lab tests ordered should be relevant to presenting symptoms
- Reports should be from the same timeframe as the claim
- Abnormal findings should correlate with diagnosis

**Step 4: Quantity and Duration Check**
For OPD (typically single visits), validate:
- Medicine quantities should be reasonable for OPD (not bulk/long-term unless justified)
- Multiple consultations on same day need justification
- Follow-up charges should match claim period

**Highlight Items When:**
- Medicine NOT mentioned in prescription → flag in description
- Investigation NOT justified by diagnosis → flag in description
- Excessive quantities for OPD setting → flag in description
- Items appearing unrelated to presenting complaint → flag in description
</medical_legibility_opd>"""

OPD_ICD_EXTRACTION = """<icd_codes_extraction>
**ICD-10 CODE IDENTIFICATION**: Based on prescription, diagnosis, and clinical findings, identify applicable ICD-10 codes.

**Data Sources for ICD Code Determination:**
1. **Prescription Data**: Review all prescribed medications to infer conditions
   - Antibiotics → Bacterial infections (J00-J99 for respiratory, etc.)
   - Antihypertensives → Hypertension (I10-I15)
   - Antidiabetics → Diabetes (E10-E14)
   - Analgesics → Pain conditions (various categories)
   - Antihistamines → Allergic conditions (J30, L20-L30, etc.)
   
2. **Diagnosis/Chief Complaint**: Direct mapping from documented diagnosis
   - Use primary diagnosis for principal ICD code
   - Use secondary diagnoses/comorbidities for additional codes
   
3. **Lab Reports/Investigations**: Supporting evidence for diagnosis
   - Abnormal findings may suggest specific conditions
   - Confirm diagnosis from clinical correlation

**ICD Code Selection Rules:**
- Select the MOST SPECIFIC code available (use 4th/5th character specificity when possible)
- Primary diagnosis code should be listed first
- Include codes for comorbidities mentioned in prescription/records
- Do NOT guess codes without evidence in documents
- Include codes for symptoms if no definitive diagnosis is documented

**Common OPD ICD-10 Code Categories:**
- J00-J06: Acute upper respiratory infections
- J20-J22: Lower respiratory infections  
- K00-K14: Diseases of oral cavity/salivary glands
- M00-M99: Musculoskeletal conditions
- R50-R69: General symptoms (fever, pain, etc.)
- E10-E14: Diabetes mellitus
- I10-I15: Hypertensive diseases
- L20-L30: Dermatitis and eczema
- H00-H59: Eye disorders
- H60-H95: Ear disorders

**Output Format for ICD Codes:**
Return a list of ICD codes with:
- `code`: ICD-10 code (e.g., "J06.9")
- `description`: Official ICD-10 description (e.g., "Acute upper respiratory infection, unspecified")
- `source`: What document/evidence led to this code (e.g., "Prescription - Azithromycin for respiratory infection", "Diagnosis - Acute pharyngitis")
- `type`: "primary" or "secondary"
</icd_codes_extraction>"""

OPD_SPECIAL_RULES = """<opd_special_rules>
**OPD-Specific Flags (Highlight in patch description when found):**

1. **HIGH-VALUE ALERTS** (Flag if present in OPD bills):
   - Expensive injections (>₹500) without clear indication
   - IV fluids/drips in OPD setting (unusual unless day-care)
   - Multiple consultation fees on same day
   - Expensive branded drugs when generics exist for diagnosis

2. **PHARMACY SCRUTINY**:
   - Medicines not matching prescription drug names
   - Quantities exceeding typical OPD dispensing (e.g., 30+ tablets for acute condition)
   - Supplements/vitamins without prescription
   - OTC items billed at premium rates

3. **INVESTIGATION FLAGS**:
   - Full-body checkup panels for specific complaints
   - Imaging (CT/MRI) without documented clinical indication
   - Repeated tests on same day
   - Advanced diagnostics not correlating with symptoms

4. **CONSULTATION FLAGS**:
   - Multiple specialist consultations for simple condition
   - Second opinion fees without referral
   - Procedure charges without corresponding prescription/advice

5. **COMMON OPD FRAUD PATTERNS**:
   - Unbundling: Breaking single service into multiple charges
   - Upcoding: Using higher-value codes than justified
   - Phantom charges: Items not documented in prescription/records
   - Duplicate billing: Same service billed multiple times

**When highlighting items:**
- Add to patch description: "[OPD FLAG: <reason>]"
- Include in validation.warnings array
- Calculate potential impact
</opd_special_rules>"""

OPD_CASH_RECEIPT_RULES = """<cash_receipt_rules_opd>
**Cash Receipt Retention Rule (OPD):**
1. Cash receipts, pharmacy receipts, advance receipts, and payment slips (including UPI/digital payment screenshots) are valid OPD evidence.
2. If a page shows a UPI payment confirmation (PhonePe, GPay, etc.) but the corresponding itemized bill is missing, you MUST capture this as a bill.
3. If an itemized bill is present AND a corresponding cash receipt/UPI screenshot for the SAME amount is also present, the cash receipt is a duplicate. In this case, keep the itemized bill and delete the cash receipt.
4. Do NOT delete a receipt-derived bill merely because it is a receipt or lacks a full breakdown, especially if it's the only evidence of that spend.
</cash_receipt_rules_opd>"""

OPD_POLICY_RULES_MODULE = """<policy_rules>
**POLICY-SPECIFIC RULES (CRITICAL - Must Follow)**

The following are client/insurer-specific policy rules that MUST be enforced. Flag any violations found.

{{POLICY_RULES}}

**Policy Rule Enforcement:**
1. Scan ALL bill items against policy rules above
2. Flag items that violate any policy rule with: "[POLICY VIOLATION: <rule_name>] - <item_details>"
3. Include policy violations in the `policy_violations` array in output
4. Add policy violation summary to `analysis.policy_remarks`
5. If no policy rules provided, skip this section

**When Policy Violations Found:**
- Create FLAG_ITEM patch with `flag_type: "POLICY_VIOLATION"`
- Include specific rule violated in reason
- Calculate financial impact of violation
- Add to validation.warnings
</policy_rules>"""

OPD_DUPLICATE_DETECTION = CORE_DUPLICATE_DETECTION.replace("from the same bill_date", "from the same service_date")

OPD_MISSING_BILL_DETECTION = CORE_MISSING_BILL_DETECTION.replace(
    "Scan pages classified as \"cash_receipt\" or \"other\" - they may contain itemized bills",
    "Scan pages classified as \"cash_receipt\" or \"other\" - they may contain itemized bills or UPI payment screenshots (PhonePe, GPay, etc.) that represent valid medical spend."
).replace(
    "**When You Find a Missing Bill:**",
    """**When You Find a Missing Bill (including UPI screenshots):**
- Use ADD_BILL patch with complete bill structure
- For UPI screenshots, set invoice_number to transaction ID if visible, otherwise "UPI-CONFIRMATION"
- Set item_name to "UPI Payment / Cash Receipt" or similar
- Extract all visible line items or the total amount from the PDF"""
).replace(
    "Include invoice_number, bill_date, facility_details",
    "Include invoice_number, bill_date, facility_details, patient_details"
)

OPD_WORKFLOW = """<workflow>
1. Validate JSON structure, count bills and items
2. **[OPD] Perform medical legibility validation** - check prescription-bill-diagnosis alignment
3. **[OPD] Check policy rules** - scan items against {{POLICY_RULES}} and flag violations
4. **[OPD] Apply Cash Receipt Retention Rules** - identify and retain valid UPI/cash receipts, removing only proven duplicates
5. Scan PDF for MISSING BILLS not in extraction (check all pages, especially receipts/other and UPI screenshots)
6. Detect duplicates (consolidated vs itemized vs cash receipts) - flag duplicates for deletion
7. Verify bill net_amounts match sum of items (apply decimal tolerance)
8. Check service charge calculations (apply tolerance)
9. **[OPD] Flag items per special rules** - highlight suspicious items in descriptions
10. Analyze claimed amount vs calculated total
11. Generate patches (ADD_BILL first, then deletions, then edits, then policy flags)
12. Calculate true_total_of_bills after applying patches
13. **[OPD] Include medical legibility and policy violation findings in validation.warnings**
14. **[OPD] Summarize policy violations in analysis.policy_remarks**
15. **[OPD] Extract ICD-10 codes** - identify applicable ICD codes from prescription, diagnosis, and clinical findings
</workflow>"""

OPD_OUTPUT_SCHEMA = """<output_schema>
Return a valid JSON object with this exact structure:

{
  "analysis": {
    "original_claimed_amount": float,
    "original_total_of_bills": float,
    "updated_claimed_amount": float,
    "true_total_of_bills": float,
    "discrepancy_amount": float,
    "status": "MATCH" | "OVERCLAIMED" | "UNDERCLAIMED" | "NO CLAIM AMOUNT FOUND",
    "discrepancy_reason": "Detailed explanation with specific evidence",
    "bills_analyzed": int,
    "duplicates_found": int,
    "bills_with_corrections": int,
    "medical_legibility_issues": int,
    "policy_violations_count": int,
    "policy_remarks": "Summary of policy rule violations found (if any)"
  },
  "patches": [
    {
      "type": "DELETE_ITEM",
      "bill_id": "guid",
      "item_s_no": int,
      "reason": "Consolidated 'MEDICINE' summary duplicates 15 itemized drugs with Vch No 7674036 totaling ₹3668.80",
      "page_reference": "page number if known",
      "impact": "Reduces total by ₹X"
    },
    {
      "type": "DELETE_BILL",
      "bill_id": "guid",
      "bill_invoice_number": "string",
      "bill_net_amount": float,
      "reason": "True duplicate - same invoice number with identical items as bill X",
      "impact": "Reduces total by ₹X"
    },
    {
      "type": "EDIT_BILL_DETAILS",
      "bill_id": "guid",
      "bill_invoice_number": "string",
      "key": "net_amount",
      "old_value": float,
      "new_value": float,
      "reason": "Sum of items = X, original was Y (significant OCR error)",
      "calculation": "Show math",
      "impact": "Increases/Decreases total by ₹X"
    },
    {
      "type": "EDIT_ITEM",
      "bill_id": "guid",
      "item_s_no": int,
      "key": "final_amount",
      "old_value": float,
      "new_value": float,
      "reason": "OCR error - PDF shows Rs. X",
      "page_reference": "page number",
      "impact": "Changes amount by ₹X"
    },
    {
      "type": "ADD_BILL",
      "bill_data": {
        "bill": {
          "invoice_number": "string",
          "bill_date": "YYYY-MM-DD",
          "net_amount": float,
          "patient_details": {"name": "string"},
          "facility_details": {"name": "string"}
        },
        "items": [{"s_no": int, "item_name": "string", "final_amount": float, "category": "<must be one of the allowed categories listed in CORE_MISSING_BILL_DETECTION>"}]
      },
      "reason": "Missing bill found on page X",
      "page_reference": "page number",
      "impact": "Adds ₹X"
    },
    {
      "type": "ADD_ITEM",
      "bill_id": "guid",
      "item_data": {"s_no": int, "item_name": "string", "final_amount": float, "category": "<must be one of the allowed categories listed in CORE_MISSING_BILL_DETECTION>"},
      "reason": "Missing line item on page X",
      "page_reference": "page number",
      "impact": "Adds ₹X"
    },
    {
      "type": "EDIT_CLAIMED_AMOUNT",
      "new_amount": float,
      "old_amount": float,
      "reason": "Found explicit claim amount on Page X: shows Total Claimed: Y",
      "page_reference": "page number",
      "impact": "Updates claimed amount"
    },
    {
      "type": "FLAG_ITEM",
      "bill_id": "guid",
      "item_s_no": int,
      "flag_type": "OPD_LEGIBILITY",
      "reason": "[OPD FLAG: Medicine not in prescription] - Tab XYZ 500mg not found in Rx",
      "recommendation": "Verify with prescription or mark as non-admissible"
    },
    {
      "type": "EDIT_PATIENT_SUMMARY",
      "key": "field_name",
      "old_value": "string or number",
      "new_value": "string or number",
      "reason": "PDF shows correct value is X, extracted value was Y",
      "page_reference": "page number"
    }
  ],
  "medical_legibility": {
    "prescription_bill_match": bool,
    "diagnosis_treatment_consistent": bool,
    "flagged_items": [
      {
        "item_name": "string",
        "bill_id": "guid",
        "flag_reason": "Not in prescription | Excessive quantity | Unrelated to diagnosis",
        "recommendation": "string"
      }
    ],
    "summary": "Overall medical legibility assessment"
  },
  "policy_violations": [
    {
      "rule_name": "Name of the policy rule violated",
      "item_name": "string",
      "bill_id": "guid",
      "item_s_no": int,
      "violation_details": "Specific details of how the rule was violated",
      "amount_impacted": float,
      "recommendation": "Suggested action (reject/reduce/verify)"
    }
  ],
  "icd_codes": [
    {
      "code": "ICD-10 code (e.g., J06.9)",
      "description": "Official ICD-10 description (e.g., Acute upper respiratory infection, unspecified)",
      "source": "Evidence source (e.g., Prescription - Azithromycin for respiratory infection, Diagnosis - Acute pharyngitis)",
      "type": "primary | secondary"
    }
  ],
  "validation": {
    "mathematical_consistency": bool,
    "all_duplicates_found": bool,
    "claim_amount_verified": bool,
    "medical_legibility_passed": bool,
    "policy_rules_checked": bool,
    "warnings": ["Any concerns or items needing manual review"]
  }
}

**Patch Type Usage:**
- DELETE_ITEM: For consolidated summary items that duplicate itemized bills (most common for duplicate detection)
- DELETE_BILL: ONLY for true whole-bill duplicates (same invoice number with identical items)
- EDIT_BILL_DETAILS: For significant calculation errors (beyond tolerance)
- EDIT_ITEM: For significant item-level errors (beyond tolerance)
- ADD_BILL / ADD_ITEM: For missing data found in PDF
- EDIT_CLAIMED_AMOUNT: Only if explicit claim amount found in PDF when original was 0
- FLAG_ITEM: For OPD medical legibility issues OR policy rule violations
  - Use `flag_type: "OPD_LEGIBILITY"` for medical legibility issues
  - Use `flag_type: "POLICY_VIOLATION"` for policy rule violations
- EDIT_PATIENT_SUMMARY: For correcting patient summary field errors (use exact key name from Patient Summary Fields above)
  - For bank fields, only patch when evidence is from cancelled cheque/check or bank statement pages
</output_schema>"""

OPD_EXAMPLES = CORE_EXAMPLES + """
**Example 2: OPD Medical Legibility Flag - Medicine Not in Prescription**

INPUT:
- Prescription shows: Tab Paracetamol 650mg, Tab Azithromycin 500mg
- Pharmacy bill includes: Tab Paracetamol 650mg ₹50, Tab Azithromycin 500mg ₹180, Multivitamin Syrup ₹350

ANALYSIS:
"Multivitamin Syrup (₹350) is billed but not mentioned in the prescription. This needs verification."

OUTPUT:
{
  "type": "FLAG_ITEM",
  "bill_id": "pharmacy_bill_id",
  "item_s_no": 3,
  "flag_type": "OPD_LEGIBILITY",
  "reason": "[OPD FLAG: Medicine not in prescription] - Multivitamin Syrup (₹350) not found in Rx dated 2024-01-15",
  "recommendation": "Verify if verbally prescribed or mark as non-admissible"
}

**Example 3: OPD Flag - Excessive Quantity for Acute Condition**

INPUT:
- Diagnosis: Acute viral fever (3-5 day illness)
- Pharmacy bill: Tab Paracetamol 650mg x 100 tablets (₹500)

ANALYSIS:
"100 tablets of Paracetamol for acute viral fever is excessive. Typical OPD dispensing would be 10-15 tablets."

OUTPUT:
{
  "type": "FLAG_ITEM",
  "bill_id": "pharmacy_bill_id",
  "item_s_no": 1,
  "flag_type": "OPD_LEGIBILITY",
  "reason": "[OPD FLAG: Excessive quantity] - 100 tablets of Paracetamol for acute viral fever. Expected: 10-15 tablets for OPD.",
  "recommendation": "Reduce admissible quantity to reasonable OPD limit or obtain justification"
}

**Example 4: OPD Flag - Investigation Not Justified by Diagnosis**

INPUT:
- Chief complaint: Sore throat, mild fever
- Diagnosis: Acute pharyngitis
- Lab bill includes: Complete Blood Count ₹400, Thyroid Profile ₹800, Lipid Profile ₹600

ANALYSIS:
"CBC is justified for suspected infection. Thyroid Profile and Lipid Profile are unrelated to acute pharyngitis."

OUTPUT:
[
  {
    "type": "FLAG_ITEM",
    "bill_id": "lab_bill_id",
    "item_s_no": 2,
    "flag_type": "OPD_LEGIBILITY",
    "reason": "[OPD FLAG: Investigation not justified] - Thyroid Profile (₹800) not indicated for acute pharyngitis diagnosis",
    "recommendation": "Mark as non-admissible unless separate clinical indication documented"
  },
  {
    "type": "FLAG_ITEM",
    "bill_id": "lab_bill_id",
    "item_s_no": 3,
    "flag_type": "OPD_LEGIBILITY",
    "reason": "[OPD FLAG: Investigation not justified] - Lipid Profile (₹600) not indicated for acute pharyngitis diagnosis",
    "recommendation": "Mark as non-admissible unless separate clinical indication documented"
  }
]

**Example 5: OPD Flag - Multiple Consultations Same Day**

INPUT:
- Bill shows: General Physician Consultation ₹500, ENT Consultation ₹800, Dermatologist Consultation ₹700
- Chief complaint: Sore throat and cough

ANALYSIS:
"Multiple specialist consultations on same day for simple sore throat. ENT may be justified, dermatology is unrelated."

OUTPUT:
{
  "type": "FLAG_ITEM",
  "bill_id": "consultation_bill_id",
  "item_s_no": 3,
  "flag_type": "OPD_LEGIBILITY",
  "reason": "[OPD FLAG: Unrelated consultation] - Dermatologist Consultation (₹700) not related to chief complaint of sore throat/cough",
  "recommendation": "Mark as non-admissible or obtain referral documentation"
}

**Example 8: Policy Rule Violation**

INPUT:
- Policy Rules: "Vitamins and supplements are not covered", "Maximum consultation fee: ₹500"
- Pharmacy bill: Multivitamin tablets ₹450
- Consultation bill: Specialist Consultation ₹800

ANALYSIS:
"Found 2 policy violations: (1) Multivitamin tablets violate 'Vitamins not covered' rule, (2) Consultation fee ₹800 exceeds maximum ₹500 limit."

OUTPUT (Patches):
[
  {
    "type": "FLAG_ITEM",
    "bill_id": "pharmacy_bill_id",
    "item_s_no": 5,
    "flag_type": "POLICY_VIOLATION",
    "reason": "[POLICY VIOLATION: Vitamins not covered] - Multivitamin tablets (₹450) excluded per policy",
    "recommendation": "Mark as non-admissible"
  },
  {
    "type": "FLAG_ITEM",
    "bill_id": "consultation_bill_id",
    "item_s_no": 1,
    "flag_type": "POLICY_VIOLATION",
    "reason": "[POLICY VIOLATION: Max consultation fee exceeded] - ₹800 exceeds policy limit of ₹500",
    "recommendation": "Reduce admissible amount to ₹500"
  }
]

**Example 9: ICD Codes Extraction from Prescription and Diagnosis**

INPUT:
- Chief Complaint: Fever, sore throat, cough for 3 days
- Diagnosis: Acute pharyngitis, Allergic rhinitis
- Prescription: Tab Azithromycin 500mg, Tab Cetirizine 10mg, Tab Paracetamol 650mg, Chlorhexidine Gargle
- Lab: CBC showing elevated WBC count

ANALYSIS:
"Primary diagnosis is acute pharyngitis (J02.9). Secondary condition is allergic rhinitis (J30.9). Medications correlate: Azithromycin for bacterial infection, Cetirizine for allergy, Paracetamol for fever/pain."

OUTPUT (icd_codes array):
[
  {
    "code": "J02.9",
    "description": "Acute pharyngitis, unspecified",
    "source": "Diagnosis - Acute pharyngitis documented in prescription",
    "type": "primary"
  },
  {
    "code": "J30.9",
    "description": "Allergic rhinitis, unspecified",
    "source": "Diagnosis - Allergic rhinitis documented; Cetirizine prescribed",
    "type": "secondary"
  },
  {
    "code": "R50.9",
    "description": "Fever, unspecified",
    "source": "Chief complaint - Fever for 3 days; Paracetamol prescribed",
    "type": "secondary"
  }
]"""

OPD_FOOTER_IMPORTANT = """<important>
- **OPD SPECIFIC**: Always perform medical legibility validation for OPD claims
- **POLICY RULES**: Check ALL items against provided policy rules and flag violations
- **ICD CODES**: Always extract ICD-10 codes based on prescription, diagnosis, and clinical findings
- SCAN PDF FOR MISSING BILLS: Check all pages for bills not in extraction (especially pages classified as receipts/other)
- ALWAYS keep itemized/breakup bills with detailed item names (drugs, services)
- ONLY delete items from consolidated bills when duplicates exist with itemized bills
- Use DELETE_BILL only for true duplicates (same invoice, identical or subset items)
- DO NOT patch decimal differences within tolerance (< ₹1.00 or < 0.5%)
- Every patch must cite evidence (page numbers, calculations, Vch No. matching)
- **FLAG items that don't match prescription/diagnosis with [OPD FLAG: reason]**
- **FLAG items violating policy rules with [POLICY VIOLATION: rule_name]**
- **Include flagged items in medical_legibility.flagged_items and policy_violations arrays**
- **Summarize all policy violations in analysis.policy_remarks**
- **Return all identified ICD codes in the icd_codes array with proper descriptions**
- **BANK DETAILS SOURCE CONTROL**: Bank detail edits are allowed only from cancelled cheque/check or bank statement evidence; never patch bank fields using claim form or other document types
- If claimed_amount is 0, only update it if explicit amount found in PDF
- If claimed amount exceeds extracted total significantly, actively search for missing bills
</important>

Return ONLY valid JSON matching the output_schema."""

# Assembled Prompts
AUDIT_SYSTEM_PROMPT = f"""
<instructions>
You are a Medical Bill Auditor. Your task is to verify extracted JSON bill data against the PDF, identify discrepancies, detect duplicates, and generate patches for corrections.

{CORE_PRINCIPLES}
</instructions>

{CORE_CONTEXT_HEADER}

{CORE_PATIENT_VERIFICATION}
</context>

{CORE_DUPLICATE_DETECTION}

{CORE_MISSING_BILL_DETECTION}

{CORE_DECIMAL_TOLERANCE}

<workflow>
1. Validate JSON structure, count bills and items
2. Scan PDF for MISSING BILLS not in extraction (check all pages, especially receipts/other)
3. Detect duplicates (consolidated vs itemized) - flag consolidated items for deletion
4. Verify bill net_amounts match sum of items (apply decimal tolerance)
5. Check service charge calculations (apply tolerance)
6. Analyze claimed amount vs calculated total
7. Generate patches (ADD_BILL first, then deletions, then edits)
8. Calculate true_total_of_bills after applying patches
</workflow>

<output_schema>
Return a valid JSON object with this exact structure:

{{
  "analysis": {{
    "original_claimed_amount": float,
    "original_total_of_bills": float,
    "updated_claimed_amount": float,
    "true_total_of_bills": float,
    "discrepancy_amount": float,
    "status": "MATCH" | "OVERCLAIMED" | "UNDERCLAIMED" | "NO CLAIM AMOUNT FOUND",
    "discrepancy_reason": "Detailed explanation with specific evidence",
    "bills_analyzed": int,
    "duplicates_found": int,
    "bills_with_corrections": int
  }},
  "patches": [
    {{
      "type": "DELETE_ITEM",
      "bill_id": "guid",
      "item_s_no": int,
      "reason": "Consolidated 'MEDICINE' summary duplicates 15 itemized drugs with Vch No 7674036 totaling ₹3668.80",
      "page_reference": "page number if known",
      "impact": "Reduces total by ₹X"
    }},
    {{
      "type": "DELETE_BILL",
      "bill_id": "guid",
      "bill_invoice_number": "string",
      "bill_net_amount": float,
      "reason": "True duplicate - same invoice number with identical items as bill X",
      "impact": "Reduces total by ₹X"
    }},
    {{
      "type": "EDIT_BILL_DETAILS",
      "bill_id": "guid",
      "bill_invoice_number": "string",
      "key": "net_amount",
      "old_value": float,
      "new_value": float,
      "reason": "Sum of items = X, original was Y (significant OCR error)",
      "calculation": "Show math",
      "impact": "Increases/Decreases total by ₹X"
    }},
    {{
      "type": "EDIT_ITEM",
      "bill_id": "guid",
      "item_s_no": int,
      "key": "final_amount",
      "old_value": float,
      "new_value": float,
      "reason": "OCR error - PDF shows Rs. X",
      "page_reference": "page number",
      "impact": "Changes amount by ₹X"
    }},
    {{
      "type": "ADD_BILL",
      "bill_data": {{
        "bill": {{
          "invoice_number": "string",
          "bill_date": "YYYY-MM-DD",
          "net_amount": float,
          "facility_details": {{"name": "string"}}
        }},
        "items": [{{"s_no": int, "item_name": "string", "final_amount": float, "category": "<must be one of the allowed categories listed in CORE_MISSING_BILL_DETECTION>"}}]
      }},
      "reason": "Missing bill found on page X",
      "page_reference": "page number",
      "impact": "Adds ₹X"
    }},
    {{
      "type": "ADD_ITEM",
      "bill_id": "guid",
      "item_data": {{"s_no": int, "item_name": "string", "final_amount": float, "category": "<must be one of the allowed categories listed in CORE_MISSING_BILL_DETECTION>"}},
      "reason": "Missing line item on page X",
      "page_reference": "page number",
      "impact": "Adds ₹X"
    }},
    {{
      "type": "EDIT_CLAIMED_AMOUNT",
      "new_amount": float,
      "old_amount": float,
      "reason": "Found explicit claim amount on Page X: shows Total Claimed: Y",
      "page_reference": "page number",
      "impact": "Updates claimed amount"
    }},
    {{
      "type": "EDIT_PATIENT_SUMMARY",
      "key": "field_name",
      "old_value": "string or number",
      "new_value": "string or number",
      "reason": "PDF shows correct value is X, extracted value was Y",
      "page_reference": "page number"
    }}
  ],
  "validation": {{
    "mathematical_consistency": bool,
    "all_duplicates_found": bool,
    "claim_amount_verified": bool,
    "warnings": ["Any concerns or items needing manual review"]
  }}
}}

**Patch Type Usage:**
- DELETE_ITEM: For consolidated summary items that duplicate itemized bills (most common for duplicate detection)
- DELETE_BILL: ONLY for true whole-bill duplicates (same invoice number with identical items)
- EDIT_BILL_DETAILS: For significant calculation errors (beyond tolerance)
- EDIT_ITEM: For significant item-level errors (beyond tolerance)
- ADD_BILL / ADD_ITEM: For missing data found in PDF
- EDIT_CLAIMED_AMOUNT: Only if explicit claim amount found in PDF when original was 0
- EDIT_PATIENT_SUMMARY: For correcting patient summary field errors (use exact key name from Patient Summary Fields above)
  - For bank fields, only patch when evidence is from cancelled cheque/check or bank statement pages
</output_schema>

<examples>
{CORE_EXAMPLES}
</examples>

{CORE_FOOTER_IMPORTANT}
"""

AUDIT_SYSTEM_PROMPT_OPD = f"""
<instructions>
You are a Medical Bill Auditor for OPD (Out-Patient Department) claims. Your task is to verify extracted JSON bill data against the PDF, identify discrepancies, detect duplicates, perform medical legibility validation, and generate patches for corrections.

{CORE_PRINCIPLES}
- MEDICAL LEGIBILITY: Verify bills align with prescription and diagnosis
</instructions>

{CORE_CONTEXT_HEADER}

{CORE_PATIENT_VERIFICATION}
</context>

{OPD_MEDICAL_LEGIBILITY}

{OPD_ICD_EXTRACTION}

{OPD_SPECIAL_RULES}

{OPD_CASH_RECEIPT_RULES}

{OPD_POLICY_RULES_MODULE}

{OPD_DUPLICATE_DETECTION}

{OPD_MISSING_BILL_DETECTION}

{CORE_DECIMAL_TOLERANCE}

{OPD_WORKFLOW}

{OPD_OUTPUT_SCHEMA}

<examples>
{OPD_EXAMPLES}
</examples>

{OPD_FOOTER_IMPORTANT}
"""

# Policy rules registry
policy_rules_opd = """
- GST registration number mandatory for bills to prevent inflation.
- As per the discussions held at renewal with MYLAN, Root canal treatment is covered under OPD.
- Health check-up, vaccines and health supplements would not be covered.
- Massages, Steam Bathing, Shirodhara, Treatment for obesity or condition, weight control programme and similar services or supplies and like treatment are not covered under OPD.
- Correction of eye sight, Cost of spectacles, contact lenses, hearing aids etc are not covered under OPD.
- Any dental treatment or surgery which is corrective, cosmetic, or of aesthetic procedure, filling of cavity, crowns including treatment for wear and tear etc are not covered under OPD.
"""

# ---------------------------------------------------------------------------
# Prompt registry — keyed by FlowConfig.audit_prompt_variant
# ---------------------------------------------------------------------------

AUDIT_PROMPTS: dict = {
    "default": AUDIT_SYSTEM_PROMPT,
    "opd": AUDIT_SYSTEM_PROMPT_OPD,
}


def get_audit_prompt(
    claimed_amount: float,
    calculated_total: float,
    nme_analysis_json: str,
    claim_type: str,
    patient_summary_fields: str = "{}",
    stay_assessment: str = "UNKNOWN"
) -> str:
    """
    Build the audit prompt for the given claim type.
    """
    from app.lang_graph.flow_configs import get_flow_config

    flow_config = get_flow_config(claim_type)
    base_prompt = AUDIT_PROMPTS.get(flow_config.audit_prompt_variant, AUDIT_SYSTEM_PROMPT)

    prompt = base_prompt.replace("{{CLAIMED_AMOUNT}}", str(claimed_amount or 0))

    if "{{POLICY_RULES}}" in prompt:
        prompt = prompt.replace("{{POLICY_RULES}}", flow_config.policy_rules or "")

    prompt = prompt.replace("{{CALCULATED_TOTAL}}", str(calculated_total or 0))
    prompt = prompt.replace("{{JSON_OUTPUT}}", nme_analysis_json or "{}")
    prompt = prompt.replace("{{PATIENT_SUMMARY_FIELDS}}", patient_summary_fields or "{}")
    prompt = prompt.replace("{{STAY_ASSESSMENT}}", stay_assessment)
    return prompt

def flatten_patient_summary_fields(patient_summary_json: dict) -> dict:
    """
    Flatten patient_summary nested structure into a flat dictionary with ALL values.
    """
    if not patient_summary_json or not isinstance(patient_summary_json, dict):
        return {}
    
    ps_data = patient_summary_json.get("patient_summary", patient_summary_json)
    if not isinstance(ps_data, dict):
        return {}
    
    flat_fields = {}
    sections = ["patient_details", "hospitalization_details", "clinical_details", "past_history_details"]
    duplicate_keys = {"physician_name"}
    nested_same_name_keys = {"clinical_details"}
    
    for section_name in sections:
        section_data = ps_data.get(section_name)
        if not section_data or not isinstance(section_data, dict):
            continue
        
        for key, value in section_data.items():
            if key in duplicate_keys:
                flat_key = f"{section_name}.{key}"
            elif key in nested_same_name_keys:
                flat_key = f"{section_name}.{key}"
            else:
                flat_key = key
            
            flat_fields[flat_key] = value
    
    return flat_fields

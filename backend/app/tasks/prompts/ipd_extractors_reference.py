# Source: healthpay-ai@test-fhpl healthpay/backend/app/lang_graph/prompts/structured_data_extractors.py

DISCHARGE_SUMMARY_STRUCTURED_DATA_EXTRACTOR = """

<instructions>
Your task is to extract the below data from the pdf file enclosed in <file></file> tags into a structured JSON object following the schema provided in <schema></schema> tags.

</instructions>

<schema>
{
    "claims_digitization_details": {

        "name_of_treating_doctor": "string",
        "treating_doctor_registration": "string",
        "type_of_nature_of_treatment": "enum: Allopathy|Ayurvedic|Homeopathy|Siddha|Unnani|Yoga|Naturopathy",
        "nature_of_treatment": "enum: Allopathy|Ayush",
        "availed_accommodation": "enum: General Ward|General Ward A/C|ICU|HDU|HDU Room|Single|Single A/C|Private|Deluxe|Suite|Semi Private|Semi Delux|Day Care|Labor Room|Post OP.|Casuality|Sharing - Double|Sharing - Triple|Sharing - Multiple|Sharing - Double A/C|Sharing - Triple A/C|Sharing - Multiple A/C",
        "date_of_admission": "YYYY-MM-DD format",
        "time_of_admission": "HH:MM format",
        "date_of_discharge": "YYYY-MM-DD format",
        "time_of_discharge": "HH:MM format",
        "diagnosis": "string",
        "presenting_complaint": "string",
        "patient_condition": "enum: Recovered|Transferred|Not Alive|LAMA",
        "ip_no": "string",
        "room_days": "number",
        "icu_days": "number",
        "duration_of_ailment": "string",
        "temperature_f": "string",
        "cvs": "string",
        "pa": "string",
        "probable_line_of_treatment": "enum: Medical|Surgical",
        "treatment_details": "string",
        "type_of_anaesthesia": "enum: General|Spinal|Epidural|Local|Regional|null",
        "route_of_drug_administration": "enum: Oral|IV|IM|SC|Topical|Inhalation",
        "admission_type": "enum: Planned|Emergency",
        "cancer": "string",
        "copd": "string",
        "medical_past_history": "string",
        "history_of_past_illness": "string",
        "is_maternity": "boolean",
        "gplad": "string",
        "lmp": "YYYY-MM-DD format",
        "date_of_delivery": "YYYY-MM-DD format",
        "accident_case": "boolean",
        "is_death_case": "boolean",
        "date_of_death": "YYYY-MM-DD format",
        "time_of_death": "HH:MM format"
    }
}
</schema>

<extraction_rules>

## Claims Details
- **name_of_treating_doctor**: Name of the primary treating physician - Look for keywords: "Dr.", "Doctor", "Consultant", "Treating Doctor", "Physician". Check signatures, letterheads, and doctor information sections. Do NOT extract patient names or other non-doctor names.
- **treating_doctor_registration**: Medical registration number of treating doctor

- **diagnosis**: Final or provisional diagnosis. NOTE: If the document mentions "provisional diagnosis" instead of "final diagnosis", treat it as the diagnosis. Extract the diagnosis from either "final diagnosis" or "provisional diagnosis" fields in the document.
- **presenting_complaint**: Main presenting complaint
- **medical_past_history**: Past medical history of the patient which is mentioned in the past history details in the discharge summary
- **history_of_past_illness**: Detailed history of past illnesses, diseases, or medical conditions mentioned in the clinical history or past medical history section of the discharge summary
- **lmp**: Last Menstrual Period date (in YYYY-MM-DD format)

## Maternity Details
- **is_maternity**: Set to TRUE for: LSCS (Lower Segment Cesarean Section), normal delivery, and other pregnancy/delivery-related procedures. If the patient is a mother who has undergone any of these procedures, set **is_maternity = true**
   Set to FALSE for: abortion, miscarriage, and other diseases or conditions that are not related to pregnancy or delivery ,  If the patient is b/o of the patient then **is_maternity = false**
- **STRICT EXCLUSION (BABY/NEWBORN CASES)**: If the patient is a baby/newborn/neonate/infant or B/O (including NICU baby admissions), set **is_maternity = false** even if the document contains terms like "delivery", "birth", "postnatal", or "LSCS". Maternity applies to the mother receiving obstetric care, not to the baby.

## Hospitalization Details
- **date_of_admission**: Date patient was admitted (in YYYY-MM-DD format)
- **date_of_discharge**: Date patient was discharged (in YYYY-MM-DD format)


## Additional Claims Details
- **type_of_nature_of_treatment**: Broad category of treatment - MUST be one of: Allopathy, Ayurvedic, Homeopathy, Siddha, Unnani, Yoga, Naturopathy
- **nature_of_treatment**: Specific nature of treatment - MUST be one of: Allopathy, Ayush
- **availed_accommodation**: Accommodation actually availed - MUST be one of the predefined accommodation types (see enum_constraints section). **CRITICAL PRIORITY RULE**: If multiple accommodation types are mentioned (e.g., both ICU and Deluxe, or both HDU and Private), prioritize room category types (Deluxe, Private, Single, Single A/C, Suite, Semi Private, Semi Delux, Sharing - Double, Sharing - Triple, Sharing - Multiple, Sharing - Double A/C, Sharing - Triple A/C, Sharing - Multiple A/C) over care-level types (ICU, HDU). Room categories represent the actual accommodation type, while ICU/HDU represent the level of care. If the accommodation type mentioned in the document does not match any of the available options or if you are unsure, default to "General Ward". If no accommodation information is present anywhere in the document, set to null.
- **time_of_admission**: Time of admission (HH:MM)
- **time_of_discharge**: Time of discharge (HH:MM)
- **patient_condition**: Patient condition - MUST be one of: Recovered, Transferred, Not Alive, LAMA
- **ip_no**: In-patient / UHID number - This is the patient registration/admission number, NOT the bill number
- **room_days**: Number of room-stay days billed
- **icu_days**: Number of ICU days billed

## Clinical Details
- **presenting_complaint**: Main presenting complaint
- **duration_of_ailment**: Duration of the ailment or condition as a string (e.g., "2 days", "1 week")
- **temperature_f**: Temperature in Fahrenheit
- **cvs**: Cardiovascular system findings
- **pa**: Per-abdomen findings
- **probable_line_of_treatment**: Planned line of treatment - MUST be one of: Medical, Surgical
- **treatment_details**: Detailed treatment description, list of surgeries performed, treatment details usually available in the discharge summary under the heading of Treatment Details,Procedure Done, Course in Hospital, Treatment given etc.
- **type_of_anaesthesia**: Anaesthesia type used usually available in the discharge summary - MUST be one of: General, Spinal, Epidural, Local, Regional, null. **CRITICAL DEFAULT RULE**: If `probable_line_of_treatment` is "Surgical" and no proper `type_of_anaesthesia` is mentioned or found in the document (i.e., the field would be null), then default `type_of_anaesthesia` to "General". Only apply this default when the treatment is Surgical and anaesthesia type is not explicitly mentioned.
- **route_of_drug_administration**: Drug administration route - MUST be one of: Oral, IV, IM, SC, Topical, Inhalation. Map "Intravenous"→"IV", "Intramuscular"→"IM", "Subcutaneous"→"SC". If value doesn't match, set to null.
- **admission_type**: Type of admission - MUST be EXACTLY one of: Planned, Emergency. Map "Elective" → "Planned", "Urgent" → "Emergency". If no clear match, set to null.

## Past History Details
- **cancer**: Look for terms like "cancer", "malignancy", "carcinoma", "tumor", "neoplasm", "oncology". Values should be "Yes", "No", or set to null. If mentioned as present/positive, use "Yes". If explicitly denied or not mentioned, use "No". If unclear, set to null.
- **copd**: Use "Yes" if condition is present/mentioned, "No" if explicitly denied/not mentioned, or set to null if information is unclear or unavailable.

## Accident Details
- **accident_case**: Boolean indicating if accident case - MUST be true or false only. Look for terms like "accident", "trauma", "injury", "RTA" (Road Traffic Accident), "fall", "motor vehicle accident". If unclear or no accident mentioned, set to false.

## Extended Maternity Details
- **date_of_delivery**: Actual delivery date
- **gplad**: Gravida / Para / Live / Abortions / Dead notation

## Death Details
- **is_death_case**: Boolean indicating death case
- **date_of_death**: Date of death
- **time_of_death**: Time of death

## Radiologist & Pathologist Details
- Capture **name**, **address**, **pincode**, **registration_number**, **email_id**, **phone_number**, **longitude**, **latitude** for each radiologist/pathologist listed. Use array order to differentiate multiple entries.

## Cancer & Critical Illness
- **type_of_cancer_treatment**: Chemo / Radiation / Immuno / Surgical etc.
- **gipsa_procedure**: Y/N flag if GIPSA package utilized
- **critical_illness_identification**: Mention specific critical illness, if any
- **no_of_chemotherapy_sessions**: Numeric count
- **no_of_immunotherapy_sessions**: Numeric count
- **dialysis_no_of_sessions**: Numeric count of dialysis sessions

## Treatment Costs
- **cost_of_implant** / **cost_of_valve_replacement** / **cost_of_pacemaker_implantation** / **cost_intravitreal_injection** / **cost_immunotherapy_injection**: Capture numeric cost values in INR


## CRITICAL Field Detection Rules

### Treating Doctor Name Detection
- Search in multiple sections: Doctor signatures, letterheads, consultant names, treating physician sections
- Look for titles: "Dr.", "Doctor", "Consultant", "Treating Doctor", "Physician", "Specialist"
- Exclude patient names, relative names, or administrative staff names
- Check discharge summary headers, prescription signatures, and doctor information blocks

### Medical Condition Detection (Cancer, Diabetes, etc.)
- **Positive indicators**: "diagnosed with", "history of", "known case of", "suffering from", "+ve", "positive"
- **Negative indicators**: "no history of", "denies", "not known", "negative", "-ve", "nil"
- **Unclear/Unknown**: Use null when information is ambiguous or not mentioned
- Values should be: "Yes" (confirmed present), "No" (confirmed absent), null (unclear/not mentioned)

### Enum Field Strict Validation
- admission_type: ONLY "Planned" or "Emergency" - map "Elective"→"Planned", "Urgent"→"Emergency"
- route_of_drug_administration: ONLY the exact enum values (Oral, IV, IM, SC, Topical, Inhalation) - map "Intravenous"→"IV", "Intramuscular"→"IM", "Subcutaneous"→"SC"
- accident_case: ONLY boolean true/false - look for accident/trauma keywords
- If value doesn't match enum exactly, set to null

## Format Instructions
- All dates should be in YYYY-MM-DD format
- All times should be in HH:MM format (24-hour format, e.g., "14:30", "09:15")
- Time fields include: time_of_admission, time_of_discharge, time_of_death
- Convert any time format with seconds (HH:MM:SS) to HH:MM format
- Ensure hours are always 2 digits (e.g., "09:15" not "9:15")

</extraction_rules>

<enum_constraints>
## CRITICAL: Enum Field Validation Rules

The following fields MUST only contain values from their respective predefined lists. If the text contains similar or related terms, map them to the closest valid enum value. If no match is found, set the field to null.

### availed_accommodation
ONLY these values are allowed:
- General Ward
- General Ward A/C
- ICU
- HDU
- HDU Room
- Single
- Single A/C
- Private
- Deluxe
- Suite
- Semi Private
- Semi Delux
- Day Care
- Labor Room
- Post OP.
- Casuality
- Sharing - Double
- Sharing - Triple
- Sharing - Multiple
- Sharing - Double A/C
- Sharing - Triple A/C
- Sharing - Multiple A/C

### nature_of_treatment
ONLY these values are allowed:
- Allopathy
- Ayush

### patient_condition
ONLY these values are allowed:
- Recovered
- Transferred
- Not Alive
- LAMA

### type_of_nature_of_treatment
ONLY these values are allowed:
- Allopathy
- Ayurvedic
- Homeopathy
- Siddha
- Unnani
- Yoga
- Naturopathy

### probable_line_of_treatment
ONLY these values are allowed:
- Medical
- Surgical

### admission_type
ONLY these values are allowed:
- Planned
- Emergency

### route_of_drug_administration
ONLY these values are allowed:
- Oral
- IV
- IM
- SC
- Topical
- Inhalation

### type_of_anaesthesia
ONLY these values are allowed:
- General
- Spinal
- Epidural
- Local
- Regional

## Enum Mapping Instructions:
1. Look for text that matches or is similar to these enum values
2. Use exact string matching first
3. If no exact match, use semantic similarity with these mappings:
   - admission_type: "Elective" → "Planned", "Urgent" → "Emergency", "Scheduled" → "Planned"
   - route_of_drug_administration: "Intravenous" → "IV", "Intramuscular" → "IM", "Subcutaneous" → "SC"
   - accident_case: Must be boolean (true/false) only
4. If no reasonable match exists, set field to null
5. NEVER create new values outside these predefined enums
6. Case-sensitive matching - use exact capitalization as shown above
7. For boolean fields (accident_case, is_maternity, etc.), only use true/false values

**Implementation Notes:**
- Enum validation utilities are available in `app.utils.enum_validators` for programmatic validation
- Use `validate_enum_fields(data)` function to automatically validate and map enum values
- See `get_valid_enum_values()` for complete list of acceptable values for each field

```

<example>
##Expected output snippet:
```json
{
    "claims_digitization_details": {

        "name_of_treating_doctor": "Dr. Srinivas",
        "treating_doctor_registration": "REG768576",
        "type_of_nature_of_treatment": "Allopathy",
        "nature_of_treatment": "Allopathy",
        "availed_accommodation": "ICU",
        "date_of_admission": "2025-01-12",
        "time_of_admission": "14:30",
        "date_of_discharge": "2025-01-15",
        "time_of_discharge": "10:00",
        "diagnosis": "Fracture of Leg",
        "patient_condition": "Recovered",
        "ip_no": "IP123456",
        "room_days": 3,
        "icu_days": 2,
        "presenting_complaint": "Pain in leg",
        "duration_of_ailment": "2 days",
        "temperature_f": "98.6",
        "cvs": "Normal",
        "pa": "Soft",
        "probable_line_of_treatment": "Surgical",
        "treatment_details": "Open reduction and internal fixation",
        "type_of_anaesthesia": "General",
        "route_of_drug_administration": "IV",
        "admission_type": "Emergency",
        "cancer": null,
        "copd": "No",
        "medical_past_history": "string",
        "history_of_past_illness": "string",
        "is_maternity": false,
        "gplad": "string",
        "lmp": "YYYY-MM-DD format",
        "date_of_delivery": null,
        "accident_case": true,
        "is_death_case": false,
        "date_of_death": null,
        "time_of_death": null,
        "investigation": "X-ray",
        "investigation_remarks": "Fracture visible",
        "remarks": "Patient stable post surgery",

    }
}
```
</example>

<file>
File is attached as PDF file
</file>

"""

PRESCRIPTION_STRUCTURED_DATA_EXTRACTOR_OPD = """

<instructions>
Your task is to extract the below data from the pdf file enclosed in <file></file> tags into a structured JSON object following the schema provided in <schema></schema> tags.

</instructions>

<schema>
{
    "claims_digitization_details": {

        "name_of_treating_doctor": "string",
        "treating_doctor_mobile": "string",
        "treating_doctor_registration": "string",
        "diagnosis": "string",
        "presenting_complaint": "string",
        "claimed_amount": "number",
        "temperature_f": "string",
        "hospital_name": "string",
        "hospital_address": "string",
        "hospital_city": "string",
        "hospital_state": "string",
        "hospital_pincode": "string",
        "hospital_phone_number": "string",
        "hospital_gst": "string",
    }
}
</schema>

<extraction_rules>
## Core Fields (OPD)
- **name_of_treating_doctor**: Primary treating physician or doctor's name(exclude patient names)
- **treating_doctor_mobile**: Contact number of treating doctor
- **treating_doctor_registration**: Medical registration number of treating doctor
- **claimed_amount**: Amount being claimed (numeric only)

## Clinical Details
- **diagnosis**: Final diagnosis or provisional diagnosis (treat them as the same)
- **presenting_complaint**
- **temperature_f**: Temperature in Fahrenheit if present

## Hospital Details
- **hospital_name** / **hospital_address**
- **hospital_city** / **hospital_state** / **hospital_pincode**
- **hospital_phone_number**
- **hospital_gst**

## Format Instructions
- Return valid, well-formed JSON only
- If a field is missing or unclear, set it to null
</extraction_rules>

<output_format>
- Return valid, legible, well-formed JSON only
- Enclose all string values in double quotes
- Format arrays and objects according to JSON standards
- Ensure all field names match the schema exactly
</output_format>

<example>
## Expected output snippet:
```json
{
  "claims_digitization_details": {
    "name_of_treating_doctor": "Dr. Anita Rao",
    "treating_doctor_mobile": "9876543210",
    "treating_doctor_registration": "REG123456",
    "diagnosis": "Viral fever",
    "presenting_complaint": "Fever and body ache",
    "claimed_amount": 1500,
    "temperature_f": "101.4",
    "hospital_name": "City Care Clinic",
    "hospital_address": "12 MG Road, Bengaluru",
    "hospital_city": "Bengaluru",
    "hospital_state": "Karnataka",
    "hospital_pincode": "560001",
    "hospital_phone_number": "08012345678",
    "hospital_gst": "29ABCDE1234F1Z5"
  }
}
```
</example>

<file>
File is attached as PDF file
</file>

"""

BANK_DETAILS_EXTRACTOR = """
<instructions>
Your task is to extract the banking details from the pdf file enclosed in <file></file> tags into a structured JSON object following the schema provided in <schema></schema> tags.
</instructions>

<schema>
{
    "bank_details": {
       "ifsc_code": "string",
        "bank_name": "string",
        "bank_branch": "string",
        "account_no": "string",
        "account_holder_name": "string",
        "account_type": "enum: Savings|Current"
    }
}
</schema>
<extraction_rules>
- ifsc_code - search for the IFSC code in the document where the bank details are mentioned.
  - **IFSC Format (CRITICAL — use this to resolve OCR ambiguity)**: An IFSC code is ALWAYS exactly 11 characters with this fixed structure:
    - Characters 1–4: LETTERS only (bank code, e.g., "SBIN", "HDFC", "ICIC"). These are NEVER digits.
    - Character 5: ALWAYS the digit zero `0` — NEVER the letter `O`. If the document shows `O` in position 5, correct it to `0`.
    - Characters 6–11: Alphanumeric (branch code). These CAN contain both letters and digits.
  - **0 vs O disambiguation rule**: OCR frequently confuses digit `0` (zero) with letter `O` (oh). Apply positional logic:
    - Position 5 must be `0` (digit). Correct `O` → `0` here unconditionally.
    - In positions 1–4 (bank code), all characters must be letters. Correct `0` → `O` here if a digit slips in.
    - In positions 6–11 (branch code), keep the character as extracted from the document; do not silently replace unless you are certain from context.
  - Always output the IFSC in UPPERCASE.
- The account_type is the type of account like Savings or Current.
  - **Account Type Mapping**: "SB account", "SB A/C", "S/B", "SB" all refer to "Savings" account.
  - **Default Rule**: If the account type is unclear, not mentioned, or you are unsure, default to "Savings".
- bank_branch - is the branch location of the bank.
- Do not hallucinate any information.
- If you are not sure about the information, leave it as null (except for account_type which should default to "Savings").
</extraction_rules>

<output_format>
- Return valid, legible, well-formed JSON only
- Enclose all string values in double quotes
- Format arrays and objects according to JSON standards
- The account_type should be one of the following: Savings, Current, Other
- Ensure all field names match the schema exactly
</output_format>


"""

GENERIC_SYSTEM_PROMPT = """
You are DocumentExtract-AI, a specialized data extraction expert. Your core function is transforming complex  documents into structured JSON data following precise schemas. You extract each data point with meticulous attention to detail, maintaining perfect schema compliance and accuracy throughout the extraction process.
"""


IDENTITY_DOCUMENT_EXTRACTOR = """
<instructions>
You are an expert document extraction AI. Extract the Identity Document numbers (PAN and Aadhaar) from the provided image/PDF into JSON format.

{patient_context}

<extraction_rules>
1. **PAN Card**:
   - Format: 10 alphanumeric characters (e.g., ABCDE1234F).
   - Action: Extract the full number.
   - Cleaning: Capitalize all letters. Remove all dashes, spaces, and special symbols.
   - If partially visible/masked: Extract visible characters. For text masks like "XXXXX1234F", replace masked chars with 'x' (e.g., "xxxxx1234F").

2. **Aadhaar Card (CRITICAL):**
   - **Visual Search**: Look for a 12-digit number.
   - **Masked/Cut-out Cards**: If the full number is not visible, look at the **BOTTOM EDGE / FOOTER** of the card. There is often an isolated block of **4 digits** (e.g., "1745" or "5740") printed near the bottom margin or QR code.
   - **Action**: Extract ANY visible digits. If you see "XXXX XXXX 1234", output "1234". If you see "XXXX XXXX 1745", output "1745".
   - **Do NOT return null** if you can see even a partial number (like the last 4 digits).
   - **Cleaning**: Remove ALL spaces, dashes, and non-numeric characters. Output should contain ONLY digits (0-9).
   - **Search Strategy**: 
     * Search BOTH front and back of the Aadhaar card
     * Check the bottom edge/footer area for isolated 4-digit blocks
     * Look near QR codes, margins, and corners
     * Check center area where number is typically displayed
   - **Note**: Ignore 16-digit Virtual IDs (VID). Focus only on 12-digit Aadhaar numbers.

3. **Priority & Fallback**:
   - First, look for IDs belonging to the Target Patient (if provided in patient context).
   - If Target Patient IDs are missing/unclear, extract *any* other valid ID found in the file (e.g., Spouse/Relative).
   - **Do not be strict about name matching.** If the ID is in the file, extract the number.
   - **PRIORITY RULE**: If a PAN or Aadhaar card is found in the document, **EXTRACT IT** even if the name on the card does not match the patient name.
</extraction_rules>

<output_format>
Return ONLY this JSON object:
{
    "pan_card_number": "string or null",
    "aadhar_card_number": "string or null"
}
</output_format>
</instructions>
"""



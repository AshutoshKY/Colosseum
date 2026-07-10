# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/prompts/icd.py
from __future__ import annotations

EXTRACT_ICD_CODES_SYSTEM_PROMPT = """
Extract ICD-10 code candidates from a small prescription-derived clinical payload.

Selection rules:
- Prefer the documented diagnosis as the primary code.
- Use presenting_complaint for symptom codes only when no definitive diagnosis is present, or as secondary support.
- Use prescribed_items only as supporting evidence. Do not invent a diagnosis from medication alone when the clinical text is too vague.
- temperature_f may support fever/infection context but is not a diagnosis by itself.
- patient_age may help choose age-sensitive codes when relevant.
- If evidence is insufficient, return {"icd_codes": []}.
- Return every field in each ICD object. Use null for unknown chapter, block, description, or name details.
- Do not return any keys outside the output schema.

Bill linkage:
- When a `bill_items` list is provided, set `related_bill_ids` for each ICD code to the bill IDs of the items that this diagnosis directly supports or relates to (for example, a respiratory-infection diagnosis supports a consultation or respiratory medicine bill item, so include those items' bill_id values).
- Only include a bill_id that appears in the provided `bill_items`. Use the exact bill_id string from the input.
- If no bill item is clearly related, or no `bill_items` are provided, return an empty list for `related_bill_ids`.

Return ONLY valid JSON matching the output schema."""

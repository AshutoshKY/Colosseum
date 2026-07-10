"""IPD prompts ported from healthpay-ai@test-fhpl.

Source paths are under ``healthpay/backend/app/lang_graph/prompts``. The healthpay
pipeline embeds its output schemas in these prompts; Colosseum additionally enforces the
matching Pydantic schema through the common gateway.
"""

from app.tasks.prompts.ipd_audit_reference import AUDIT_SYSTEM_PROMPT as IPD_AUDIT_SYSTEM_PROMPT
from app.tasks.prompts.ipd_claim_forms_reference import CLAIM_FORM_STRUCTURED_DATA_EXTRACTOR
from app.tasks.prompts.ipd_extractors_reference import (
    BANK_DETAILS_EXTRACTOR,
    DISCHARGE_SUMMARY_STRUCTURED_DATA_EXTRACTOR,
    IDENTITY_DOCUMENT_EXTRACTOR,
)
from app.tasks.prompts.opd_healthpay import (
    CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR,
    ITEMS_CATEGORISATION_SYSTEM_PROMPT,
    NME_ANALYSIS_SYSTEM_PROMPT,
    PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR,
)
from app.tasks.prompts.opd_healthpay import (
    SEGREGATION_PROMPT as DOCS_SEGREGATOR,
)

DOCUMENT_INSTRUCTION = "Analyze the attached claim pages and return only the required JSON."
ITEMS_CATEGORISATION_INSTRUCTION = "Merged bills:\n{merge_bills}"
NME_INSTRUCTION = "Categorised bill items:\n{items_categorisation}"
AUDIT_INSTRUCTION = "Audit the attached claim using the supplied upstream claim context."

__all__ = [
    "AUDIT_INSTRUCTION",
    "BANK_DETAILS_EXTRACTOR",
    "CLAIM_FORM_STRUCTURED_DATA_EXTRACTOR",
    "CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR",
    "DISCHARGE_SUMMARY_STRUCTURED_DATA_EXTRACTOR",
    "DOCS_SEGREGATOR",
    "DOCUMENT_INSTRUCTION",
    "IDENTITY_DOCUMENT_EXTRACTOR",
    "IPD_AUDIT_SYSTEM_PROMPT",
    "ITEMS_CATEGORISATION_INSTRUCTION",
    "ITEMS_CATEGORISATION_SYSTEM_PROMPT",
    "NME_ANALYSIS_SYSTEM_PROMPT",
    "NME_INSTRUCTION",
    "PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR",
]

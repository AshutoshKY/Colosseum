# 02 — Context: Reference Pipelines (OPD superclaims-ai · IPD healthpay-ai)

> Self-contained reports of the two production pipelines Colosseum must mirror.
> OPD = superclaims-ai branch `test-ekincare-v2` (checked out — read the working tree at
> `/Users/ekincare/superclaims/superclaims-ai`).
> IPD = healthpay-ai branch `test-fhpl` (**NOT checked out**; read via
> `git -C /Users/ekincare/superclaims/healthpay-ai show test-fhpl:<path>`,
> list with `git -C … ls-tree -r test-fhpl --name-only`). Never modify these repos.

---

# PART 1 — OPD: superclaims-ai `test-ekincare-v2`

Paths rooted at `backend/app/` of that repo.

## 1.1 Framework

LangGraph `StateGraph(AgentState)` with **config-driven topology from TOML profiles** per
client/claim-type, with inheritance (`extends`):
- Graph builder: `lang_graph/graph.py` (`compile_graph`/`build_graph`; wires `edges`,
  `fan_ins` = multi-source join barriers, START→entry, terminal→END; checkpointer in
  `lang_graph/checkpointing.py`).
- Node registry: `lang_graph/registry.py::NODE_REGISTRY` (name → callable).
- Profile schema: `lang_graph/config/models.py` (`GraphProfile`, `GraphNode`, `NodeRuntime`,
  `GraphEdge`, `FanInEdge`; `ModelKey`, `ThinkingLevel = LOW|MEDIUM|MINIMAL`).
- Loader (TOML + extends merge): `lang_graph/config/loader.py`.
- Profiles: `clients/base/graph/opd.toml` ← extended by `clients/ekincare/graph/opd.toml`.
- Invocation: `services/adjudication.py::process_claim()` builds initial state, calls
  `graph.ainvoke(...)`; driven by Temporal (`workers/workflows.py`, `activities.py`).

## 1.2 Effective ekincare-OPD flow

```
START → segregation_agent → store_segments → ekincare_policy_extraction_agent → fan-out:
  ├ claim_form_agent → store_claim_form → identity_document_agent → store_identity_document
  ├ prescription_agent → store_prescription
  ├ itemized_bills_agent ─┐
  ├ consolidated_bills_agent ┴→ merge_bills → store_bills → items_categorisation_agent
  │                                              └→ nme_analysis_agent → store_nme_analysis
  └ cheque_bank_agent → store_cheque_bank
FAN-IN [store_prescription, store_bills] → extract_icd_codes_agent → store_icd_codes
FAN-IN [store_claim_form, store_identity_document, store_prescription, store_cheque_bank,
        store_nme_analysis] → build_patient_summary → store_patient_summary → benefit_plan_agent
FAN-IN [benefit_plan_agent, store_icd_codes] → audit_agent
audit_agent → fwa_invoice_duplicate → store_audit → validation → completion → END
```

Base-vs-ekincare: base fans out straight from `store_segments` (no policy extraction, no
benefit_plan, no fwa; `store_nme_analysis → audit_agent` directly); ekincare disables
`lab_report_agent`. No conditional edges — static fan-out + fan-in barriers.
`store_*` nodes are DB persistence. Deterministic (no-LLM) nodes: `merge_bills`,
`build_patient_summary`, `fwa_invoice_duplicate`, `validation`, `completion` (in
`lang_graph/nodes/`).

## 1.3 LLM configuration

- Client: `lang_graph/llm/client.py::get_chat_model(model_key, thinking_budget,
  thinking_level, max_output_tokens)` → `ChatGoogleGenerativeAI(vertexai=True,
  temperature=0.0, timeout=300.0, max_retries=3, project=…, credentials=…)` (SA JSON from
  `google_credentials_json`).
- **Structured output ALWAYS**: `model.with_structured_output(schema, method="json_schema")`
  (`lang_graph/llm/structured.py::ainvoke_structured`).
- Model keys (`core/config.py::LLMSettings` ~135–176): `gemini_2_5_flash`→gemini-2.5-flash,
  `gemini_2_5_pro`→gemini-2.5-pro, `gemini_3_flash`→gemini-3-flash-preview,
  `gemini_3_pro`→**gemini-3.1-pro-preview**, `gemini_3_flash_lite`→gemini-3.1-flash-lite.
  `audit_max_output_tokens=16000`.
- Thinking: gemini-3* (non-lite) → `thinking_level` (default low); others →
  `thinking_budget`. Per-node values from TOML `runtime` blocks (`model_key`,
  `thinking_budget`/`thinking_level`, `timeout_seconds`, `optional`, `enabled`,
  `retry_policy`).
- Message shapes: PDF agents `[SystemMessage(prompt), HumanMessage([text, {type:"file",
  mime_type:"application/pdf", base64:…}])]`; text agents `[SystemMessage(prompt),
  HumanMessage(json.dumps(payload))]` (`lang_graph/agents/_common.py::invoke_pdf_agent /
  invoke_text_agent`).

## 1.4 Agent inventory (prompt · schema · runtime · inputs)

Prompts in `lang_graph/prompts/`, schemas in `lang_graph/schemas/` (aggregated in
`outputs.py`).

| Agent | Prompt | Runtime | Schema | Inputs |
|---|---|---|---|---|
| segregation_agent | `prompts/segregation.py::DOCS_SEGREGATOR_SYSTEM_PROMPT` + `build_ekincare_opd_document_check_prompt(benefits)` appended when ekincare-OPD & benefits present | gemini_3_flash · thinking LOW · timeout 120 | `schemas/segregation.py::DocumentSegregatorOutput{segments:[DocumentSegment{document_type: Literal[claim_forms, cheque_or_bank_details, identity_document, itemized_bill, consolidated_bill, discharge_summary, prescription, investigation_report, cash_receipt, other], pages:str}], required_documents_check: RequiredDocumentsCheck\|None}` | full PDF base64; `benefits` |
| ekincare_policy_extraction_agent | `prompts/ekincare.py::EKINCARE_POLICY_EXTRACTION_SYSTEM_PROMPT` | gemini_2_5_flash · thinking 0 | `schemas/ekincare.py::EkincarePolicyExtractionOutput{nme_items[], policy_rules[], extraction_ok, source}` | `state.policy` / `original_client_payload["policy"/"policy_details"]` — text, no PDF |
| claim_form_agent | `prompts/claim_forms.py::CLAIM_FORM_SYSTEM_PROMPT` | gemini_2_5_flash · 0 | `schemas/claim_form.py::ClaimFormOutput` (PartA/PartB, Gender enum) | claim_forms pages |
| prescription_agent | `prompts/documents.py::PRESCRIPTION_SYSTEM_PROMPT` | gemini_2_5_flash · 0 · retry standard | `schemas/discharge_summary.py::PrescriptionOutput` (claims_digitization_details: diagnosis, presenting_complaint, prescribed_items, temperature_f, patient_age, …) | prescription pages |
| discharge_summary_agent (registered, not wired in ekincare OPD) | `prompts/documents.py::DISCHARGE_SUMMARY_SYSTEM_PROMPT` | gemini_2_5_flash | `DischargeSummaryOutput` | discharge_summary pages |
| itemized_bills_agent | `prompts/bills.py::ITEMIZED_BILLS_SYSTEM_PROMPT` (composed of `_BILL_AMOUNT_RULES`, `_FACILITY_DETAILS_RULES`) | gemini_2_5_flash · thinking 8000 | `schemas/bills.py::ItemizedBillsOutput{bills:[{bill:BillHeader, items:[ItemizedBillItem]}]}` | itemized_bill pages |
| consolidated_bills_agent | `prompts/bills.py::CONSOLIDATED_BILLS_SYSTEM_PROMPT` | gemini_2_5_flash · 8000 | `ConsolidatedBillsOutput` | consolidated_bill pages |
| cheque_bank_agent (optional) | `prompts/documents.py::CHEQUE_BANK_SYSTEM_PROMPT` | gemini_2_5_flash · 0 | `schemas/bank_identity.py::BankDetailsOutput` | cheque_or_bank_details pages |
| identity_document_agent (optional) | `prompts/documents.py::IDENTITY_DOCUMENT_SYSTEM_PROMPT` | gemini_2_5_flash · 0 | `schemas/medical_documents.py::IdentityDocumentOutput` | identity_document pages |
| extract_icd_codes_agent (TEXT) | `prompts/icd.py::EXTRACT_ICD_CODES_SYSTEM_PROMPT` | gemini_2_5_flash · 0 | `schemas/icd.py::ExtractIcdCodesOutput{icd_codes:[IcdCodeCandidate{code,name,diagnosis,description,chapter,block,source,type,related_bill_ids}]}` | prescription digitization fields + compact `{bill_id,item_name}` list from merged bills (`agents/extract_icd_codes.py::build_icd_payload`) |
| items_categorisation_agent (TEXT) | `prompts/bills.py::ITEMS_CATEGORISATION_SYSTEM_PROMPT`; input via `prepare_categorization_input(bill_data)` | gemini_2_5_flash · 8000 | `ItemsCategorisationOutput{bill_item_categories:[{bill_id, categorized_items:[{s.no., category}]}]}` | merged bills |
| nme_analysis_agent (TEXT) | `prompts/nme.py::get_nme_system_prompt(include_policy_violations)` — composed of NME_ANALYSIS_INSTRUCTION/SCHEMA/RULES/STEPS/EXAMPLE/ITEMS_DEF/FALSE_POSITIVES; input via `prepare_nme_analysis_input(bills, policy_ctx)` | gemini_2_5_flash · 8000 | `NmeAnalysisOutput` (+`policy_violations:[NmePolicyViolation]` when ekincare OPD + policy_rules) | categorised bills + policy context (policy_rules / nme_items) |
| benefit_plan_agent (ekincare only, TEXT) | `prompts/ekincare.py::EKINCARE_BENEFIT_PLAN_SYSTEM_PROMPT`; input via `prepare_benefit_plan_input(...)` | gemini_2_5_flash · thinking 2048 | `schemas/ekincare.py::BenefitPlanSelectionOutput{plan_applicability[], item_assignments[]}` | benefits + categorised/merged bills + policy_extraction + document-check context + partial_doc_failure + clinical context (diagnosis/complaint/doctor spec) |
| audit_agent | `prompts/audit.py::AUDIT_SYSTEM_PROMPT` via `get_audit_prompt(calculated_total, bill_audit_json)` — replaces `{{CALCULATED_TOTAL}}`, `{{JSON_OUTPUT}}` | TOML: gemini_3_flash · LOW (code default gemini_3_pro applies only if profile omits model_key) · max_output_tokens 16000 | `schemas/adjudication.py::BillAuditOutput{original_total_of_bills, corrected_total_of_bills, discrepancy_amount, bills_analyzed, duplicates_found, bills_with_corrections, mathematical_consistency, patches:[AuditPatch{type: DELETE_BILL\|DELETE_ITEM\|EDIT_BILL_DETAILS\|EDIT_ITEM\|ADD_BILL\|ADD_ITEM, bill_id, item_s_no, reason, page_reference, impact, key, old_value, new_value, calculation, bill_data, item_data}]}` | bill JSON = nme_analysis (fallback merge_bills) + PDF pages of non-"other" segments (`agents/audit.py::_extract_relevant_pages`); `calculate_bill_total` from `utils/bills.py`; patches applied via `utils/audit.py::apply_audit_patches` → `state.bill_data` |

Deterministic nodes: `merge_bills` (join itemized+consolidated);
`build_patient_summary` (`nodes/build_patient_summary.py` → `utils/patient_data.py::
PatientDataAggregator` → `PatientSummaryOutput{patient_summary: dict[str, dict]}` from
claim_form/discharge/prescription/bills/lab/cheque/identity);
`fwa_invoice_duplicate` (DB duplicate check, `services/fwa/invoice_duplicate_checker.py`,
10s timeout); `validation` (`nodes/validation.py` → `ValidationOutput`);
`completion` (aggregates everything into the review payload).

## 1.5 State & data flow

`lang_graph/state.py::AgentState(TypedDict, total=False)`; reducers `take_first`
(claim_id/project/claim_type), `take_last` (most), append (`extracted_data`, `trace`).
Primary channel: `extracted_data: list[{node, claim_id, data}]`; read back via
`utils/extracted_data.py::find_extracted_data(state, node_name)`. `_common.output_update()`
also maps outputs to dedicated keys: policy→`policy`+`benefits`,
ekincare_policy→`policy_extraction`/`policy_nme_items`/`policy_rules`,
benefit_plan→`benefit_plan_breakdown`, build_patient_summary→`patient_summary`,
extract_icd_codes→`icd_codes`, audit→`audit_analysis`/`audit_patches`,
validation→`validation_scores`.

## 1.6 PDF handling

Native base64 PDF part (`{"type":"file","mime_type":"application/pdf","base64":…}`) — no
OCR/rasterization. Per-agent page crops via `lang_graph/utils/pdf.py::
extract_pages_as_base64(file_path, page_ranges)` (pypdf; on failure returns full PDF).
Segregation gets all pages; each extractor gets only its doc-type pages (ranges like
`"1-3,7"` from segments); audit gets all non-"other" pages.

## 1.7 Dependency map for subset runs (what to feed if upstream unselected)

- segregation ← `file_path` (+`benefits` for ekincare doc-check). Produces `segments`.
- claim_form / prescription / itemized_bills / consolidated_bills / cheque_bank /
  identity_document ← `segments` + `file_path` (independent of each other).
- ekincare_policy_extraction ← `policy` text/JSON.
- merge_bills ← itemized + consolidated outputs.
- items_categorisation ← merge_bills output.
- nme_analysis ← categorisation (or merge_bills) + policy context.
- extract_icd_codes ← prescription output + merged bills.
- build_patient_summary ← claim_form + prescription + bills + cheque_bank + identity (+ lab).
- benefit_plan ← benefits + categorised/merged bills + policy_extraction + clinical context.
- audit ← nme_analysis (fallback merge_bills) + segments + PDF.
- validation ← bill_data/nme/merge + patient_summary + claimed amount
  (`original_client_payload`).

---

# PART 2 — IPD: healthpay-ai `test-fhpl`

Read ONLY via `git show test-fhpl:<path>`. Paths rooted at
`healthpay/backend/app/lang_graph/` unless noted.

## 2.1 Framework

LangGraph (`StateGraph`, conditional edges, `langgraph.types.Send` fan-out) + LangChain
`ChatGoogleGenerativeAI` on Vertex. Graph built per claim type from `FlowConfig`
(`flow_configs.py`) and cached (`graph.py::build_graph/get_graph`). Invoked by
`app/workers/claim_processor.py` (~:158): PDF downloaded from MinIO to temp file; initial
state `{"file_path", "claim_id", "flow_type", "claim_type", "turn"}`.

FlowConfig variants: CL/RM = default; **PP skips consolidated_bills_agent**; OPD uses
prescription clinical extractor + OPD audit prompt/policy rules + flash audit model.
`FlowConfig.agent_overrides` (`AgentConfig`: system_prompt, continuation_prompt,
continuation_system_prompt, model, thinking_budget, thinking_level) currently used for
audit (OPD→flash) and available for segregation.

## 2.2 Flow

```
START → check_size ──route_by_size──▶ input(=segregation_node)          (≤50 pages)
                                  └──▶ segregate_half ×2 (Send fan-out) (>50 pages)
segregate_half → merge_segments → passthrough ;  input → passthrough
passthrough fans out to 5 parallel branches:
  ├ clinical_agent (discharge_summary; OPD: prescription) → store_clinical
  ├ itemized_bills_agent ─┐
  ├ consolidated_bills_agent ┴→ bills_agent (merger, no LLM) → store_bills
  │        → items_categorisation_agent → nme_analysis_agent → store_nme_analysis
  ├ claim_form_agent → store_claim_form → ids_agent → store_ids
  └ cheque_or_bank_details_agent → store_cheque_or_bank_details
[store_clinical, store_cheque_or_bank_details, store_ids]
  → patient_summary_agent (no LLM, DB aggregation) → store_patient_summary
[store_nme_analysis, store_patient_summary] → audit_agent → validation_agent
  → completion_aggregator → END
```

`PAGE_SPLIT_THRESHOLD = 50` (`agents/file_segregation_agent.py`). `ids_agent` deliberately
sequenced after `store_claim_form` so it can read `patient_name`.

## 2.3 ⚠️ Critical fidelity fact — NO structured output

healthpay agents do **not** use `with_structured_output`. Each call sends the PDF (base64
media block) + a system prompt that **describes the JSON schema in text**; the raw string is
parsed with `json.loads` + `json_repair` (`utils/llm_utils.py::clean_json_response`), with a
**continuation loop** up to `MAX_CONTINUATIONS = 12` on MAX_TOKENS (re-prompt with
`` `previous_json` `` replacement, truncate points like `PHARMACY_BILL_TRUNCATE_POINT`).
The Pydantic models (`models/document_segregator.py`, `models/pharmacy_bill.py`,
`models/nme_analysis.py`, `prompts/schema/*.py`) are for downstream parsing/validation only.

LLM client: `utils/llm_utils.py::process_file_with_llm` (SystemMessage + HumanMessage
`[{type:"media", data:<b64 pdf>, mime_type:"application/pdf"}]`, retry/backoff on
429/500/503, `InMemoryRateLimiter(10 rps, bucket 15)`) and `process_text_with_llm`.
`utils/utils.py::load_chat_model(model_name, temperature=0.0, thinking_budget=0,
thinking_level=None)` → `ChatGoogleGenerativeAI(model, project, location="global",
temperature=0.0, vertexai=True)`; gemini-3* → thinking_level, else thinking_budget.

Constants (`constants.py`): `GEMINI_MODEL="gemini/gemini-2.5-flash"`,
`GEMINI_3_FLASH_MODEL="gemini/gemini-3-flash-preview"`,
`GEMINI_3_PRO_MODEL="gemini/gemini-3.1-pro-preview"`, `GEMINI_LITE_MODEL`,
`GEMINI_THINKING_MODEL="gemini/gemini-2.5-pro"`, `THINKING_BUDGET=8000`,
`DEFAULT_TEMPERATURE=0.0`, `MAX_CONTINUATIONS=12`.

## 2.4 Agent inventory

Extractors built by factory `agents/data_extraction_agent.py::create_node(document_type,
system_prompt, model, …)`: read `segments["aggregated_segments"][doc_type]["page_ranges"]`,
crop pages → base64 sub-PDF (`utils/pdf_file_utils.py::extract_ranges_to_one_pdf_base64`,
PyPDF2), call LLM, remap reported page numbers back to original numbering, return
`{EXTRACTED_DATA: [{doc_type: response}], CLAIM_ID}`.

| Agent (node) | Prompt | Template vars | Model / thinking | Parsing schema | Inputs |
|---|---|---|---|---|---|
| segregation (`input`) + `segregate_half` | `prompts/prompts.py::DOCS_SEGREGATOR` ("DocAnalytics-AI" persona) | none | 3-flash · LOW | `models/document_segregator.py::DocumentSegregatorResponse{total_pages, segments:[{document_type, pages:"2-3,8", format, quality_assessment, additional_notes, critical_elements}], overall_assessment}` → post-processed by `utils/utils.py::aggregate_documents` → `{"aggregated_segments":{doc_type:{page_ranges:[{start,end}], total_pages}}}` | full PDF; claim_id, flow_type, claim_type. OPD special-case: cash_receipt merged into itemized_bill bucket |
| discharge_summary (clinical) | `prompts/structured_data_extractors.py::DISCHARGE_SUMMARY_STRUCTURED_DATA_EXTRACTOR` | none | 3-flash · MINIMAL | text-schema in prompt (claims_digitization_details…) | discharge_summary **+ consolidated_bill** pages |
| prescription (OPD clinical) | `PRESCRIPTION_STRUCTURED_DATA_EXTRACTOR_OPD` | none | 3-flash · MINIMAL, budget 0 | text-schema | prescription pages |
| itemized_bills | `prompts/bills.py::PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR` + continuation prompts | continuation: `` `previous_json` `` | 2.5-flash · budget 8000 | `models/pharmacy_bill.py::PharmacyBillStructuredData/PharmacyBillItem`; output `{bills:[{bill:{…, bill_id, bill_type}, items:[…]}]}` | itemized_bill pages |
| consolidated_bills | `CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR` | continuation | 2.5-flash · 8000 | same bill schema (`bill_type="consolidated_bill"`) | consolidated_bill pages |
| claim_form | `prompts/claim_forms.py::CLAIM_FORM_STRUCTURED_DATA_EXTRACTOR` (+ `prompts/schema/claim_form_schema.py`) | none | 2.5-flash · 0 | text-schema | claim_forms pages |
| cheque_or_bank_details | `structured_data_extractors.py::BANK_DETAILS_EXTRACTOR` | none | 3-flash · 0 | text-schema | cheque_or_bank_details pages |
| ids_agent (identity) | `IDENTITY_DOCUMENT_EXTRACTOR` | `{patient_context}` ← `state["patient_name"]` (string replace) | 2.5-flash · 0 | text-schema | identity_document pages + patient_name |
| items_categorisation | `prompts/bills.py::ITEMS_CATEGORISATION_SYSTEM_PROMPT` (fixed category list) | none | 2.5-flash · 8000 | returns `bill_item_categories`, merged onto bills. **Fuzzy DB pre-pass**: `ItemCategoryMappingRepository.bulk_fuzzy_search_categories` (0.95) | merged `pharmacy_bills` |
| nme_analysis | per-insurer via `utils/nme_prompt_builder.py::get_nme_prompt_for_claim(claim_id)` (base `prompts/nme.py`) | provider rules injected | 2.5-flash · 8000; **bypassed for OPD** | `models/nme_analysis.py::NMEAnalysisResponse/NMEItem{s_no, item_name, bill_amount, deductible_amount, admissible_amount, deduction_reason}` | categorised_items + claim_id + claim_type |
| patient_summary (no LLM) | `agents/patient_data_aggregator.py::PatientDataAggregator.aggregate_patient_data_with_mapper` | n/a | — | `PatientSummaryData` — 4 sections: patient_details, hospitalization_details, clinical_details, past_history_details | **reads stored docs from DB by claim_id** (claim form, clinical, bank, ids); OPD maps prescription→discharge slot |
| audit (`nodes/audit_nodes.py::audit_node`) | `prompts/audit.py::get_audit_prompt(claimed_amount, calculated_total, nme_analysis_json, claim_type, patient_summary_fields, stay_assessment)`; base prompt `AUDIT_PROMPTS = {"default": AUDIT_SYSTEM_PROMPT, "opd": AUDIT_SYSTEM_PROMPT_OPD}` chosen by `FlowConfig.audit_prompt_variant`; modular blocks CORE_PRINCIPLES / CORE_CONTEXT_HEADER / CORE_PATIENT_VERIFICATION / CORE_DUPLICATE_DETECTION / CORE_MISSING_BILL_DETECTION / CORE_DECIMAL_TOLERANCE / CORE_EXAMPLES + OPD_* variants | `{{CLAIMED_AMOUNT}} {{CALCULATED_TOTAL}} {{JSON_OUTPUT}} {{PATIENT_SUMMARY_FIELDS}} {{POLICY_RULES}} {{STAY_ASSESSMENT}}` | **3.1-pro · MEDIUM** (OPD → 3-flash) | returns `{analysis:{status, discrepancy_reason,…}, patches:[…], validation:{…}}` (no Pydantic constraint) | `nme_analysis_parsed` + `patient_summary_parsed` (flattened via `flatten_patient_summary_fields`) + computed claimed_amount & `calculate_total_amount_from_nme_analysis` + PDF pages of all doc types EXCEPT `FlowConfig.audit_excluded_doc_types` (default {other, investigation_report}) |
| validation (no LLM) | deterministic bill/amount/categorization math | n/a | — | `ValidationScores` | nme_analysis_parsed, patient_summary_parsed, segments |
| completion_aggregator (no LLM) | builds review payload | n/a | — | uses NMEAnalysisData, PatientSummaryData, ValidationScores | audit outputs + validation_scores |

Audit patches: `apply_audit_patches` supports DELETE_BILL, DELETE_ITEM, EDIT_BILL_DETAILS,
EDIT_ITEM, ADD_BILL, ADD_ITEM, **EDIT_CLAIMED_AMOUNT, EDIT_PATIENT_SUMMARY** (flat-key →
section mapping via `map_flat_key_to_patient_summary_path`). Audit returns edited
`nme_analysis_parsed`/`patient_summary_parsed` + `*_original` + `audit_analysis`,
`audit_full_data`, `audit_patches`; persists raw+parsed as
`document_type="audit_analysis"`.

## 2.5 State

`models/state.py::AgentState(TypedDict, total=False)`; reducers `take_first` (claim_id),
`take_last`, `operator.add` (lists). Keys: file_path, file_data (b64, re-extraction only),
claim_id, turn, flow_type, claim_type, `nme_analysis_parsed`, `patient_summary_parsed`,
`patient_name`, audit keys, page-split keys (page_count, half_start/end,
partial_segments). Subclasses add `segments`, `extracted_data (add)`, `processing_status`,
`validation_scores`.

## 2.6 Dependency map for subset runs

Data flows through state AND Postgres (store nodes write `raw_extracted_data`;
patient_summary and audit re-read from DB). To run standalone, supply:
- segregation ← file_path, claim_id, flow_type, claim_type → produces `segments`.
- extractors ← segments (their doc-type ranges) + file_path; ids also needs patient_name.
- bill_merger ← extracted_data with itemized_bill / consolidated_bill entries.
- items_categorisation ← merged pharmacy_bills (+ DB fuzzy table in prod; in Colosseum the
  LLM-only path is used).
- nme_analysis ← categorised_items + claim_id + claim_type.
- patient_summary ← stored claim_form + clinical + bank + ids data.
- **audit ← {claim_id, file_path, claim_type, nme_analysis_parsed (post-store shape
  `{bills:[{bill, items}]}`), patient_summary_parsed (4-section dict), segments}.**
- validation ← nme_analysis_parsed + patient_summary_parsed + segments.

## 2.7 PDF handling

MinIO → temp file → `file_path`. `utils/pdf_file_utils.py` (PyPDF2): `get_pdf_page_count`,
`load_pdf_file` (→b64), `extract_ranges_to_one_pdf_base64(path, page_ranges)`. No
OCR/rasterization — native PDF to Gemini. >50-page PDFs split in half for segregation only;
cropped sub-PDF page numbers remapped back to original numbering (`_remap_page_number`).

## 2.8 Stale docs warning

`healthpay/docs/backend/lang-graph.md` mentions gemini-1.5/gpt-4o-mini/OpenAI — stale.
Trust the code on branch `test-fhpl`, not that doc.

---

# PART 3 — What Colosseum already vendored

Per Colosseum `docs/phase-2.5-prompt-sourcing.md`, `tasks/prompts/opd_healthpay.py` already
contains verbatim copies of: segregation, itemized_bills, items_categorisation, nme, audit
(from healthpay-ai) and benefit_plan, policy_extraction (from superclaims-ai). WS C ports
the REMAINING agents and the IPD-specific prompt variants, and records provenance for all.

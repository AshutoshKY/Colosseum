# 05 — Workstream C: Task Packs (Full IPD Port · OPD Parity · Gold Format Extension)

> Prerequisites: read `00-master-plan.md` (§6.2 Task protocol contract), `01-context-colosseum.md`
> §5–6, and **all of `02-context-reference-pipelines.md`** (your primary source). The IPD
> reference is healthpay-ai branch `test-fhpl` — read files ONLY via
> `git -C /Users/ekincare/superclaims/healthpay-ai show test-fhpl:<path>`.

## Goal

1. Build the **IPD task pack** mirroring healthpay-ai `test-fhpl` — every agent, prompt
   (verbatim), output schema, deterministic transform, and per-agent runtime params.
2. Extend the **OPD pack** to full parity with superclaims-ai `test-ekincare-v2` and attach
   reference runtime params to all tasks.
3. Extend the **gold/ground-truth format** so any task's output can be fed as upstream input
   for subset runs (both packs).

WS A defines the extended `Task` fields (`depends_on`, `deterministic`, `reference_runtime`,
`gold_feed_keys`) and `TaskPack` — code against that contract (00 §6.2); if WS A hasn't
merged yet, create the dataclass extensions yourself in `tasks/base.py` exactly per contract
(coordinate via the contract, not via chat).

## Deliverables

| File | Action |
|---|---|
| `backend/app/tasks/prompts/ipd_healthpay.py` | NEW — verbatim IPD prompts from test-fhpl |
| `backend/app/tasks/schemas/ipd_healthpay.py` | NEW — Pydantic output schemas |
| `backend/app/tasks/ipd.py` | NEW — `IPD_TASKS`, `IPD_PIPE_ORDER`, input builders, deterministic transforms, variants |
| `backend/app/tasks/claim_types/ipd.py` | replace NotImplementedError stubs — `get_task_pack("IPD")` (+variant) |
| `backend/app/tasks/opd.py` | add `depends_on` / `reference_runtime` / `gold_feed_keys` to all 8 tasks; add parity tasks |
| `backend/app/tasks/prompts/opd_superclaims.py` | NEW — prompts for OPD parity agents (claim_form, prescription, identity, cheque_bank, icd) from superclaims-ai |
| `backend/app/tasks/schemas/opd_superclaims.py` | NEW — matching schemas |
| `backend/app/scoring/report.py` | extend `NON_SCORED_TASKS` (upstream feed keys) |
| `backend/app/scoring/ground_truth_import.py` + `docs/ground-truth-format.md` | accept new task keys; document |
| `backend/tests/test_ipd_tasks.py`, `test_opd_parity.py` | NEW |

## Part 1 — IPD pack (from healthpay-ai `test-fhpl`)

### Source files to port (read with `git show test-fhpl:<path>`; roots at `healthpay/backend/app/`)

- Prompts: `lang_graph/prompts/prompts.py` (DOCS_SEGREGATOR),
  `lang_graph/prompts/structured_data_extractors.py` (discharge, prescription-OPD, bank,
  identity), `lang_graph/prompts/bills.py` (pharmacy/consolidated bill extractors +
  continuation prompts + ITEMS_CATEGORISATION), `lang_graph/prompts/claim_forms.py` +
  `lang_graph/prompts/schema/claim_form_schema.py`, `lang_graph/prompts/nme.py` +
  `lang_graph/utils/nme_prompt_builder.py`, `lang_graph/prompts/audit.py` (ALL modular
  blocks + both variants + `get_audit_prompt`).
- Parsing models (→ Pydantic schemas): `lang_graph/models/document_segregator.py`,
  `models/pharmacy_bill.py`, `models/nme_analysis.py`, `prompts/schema/*.py`, plus the
  patient-summary section shapes in `nodes/patient_summary_nodes.py::_parse_patient_summary`
  and `agents/patient_data_aggregator.py`.
- Deterministic logic: `agents/pharmacy_bills_agent.py::bill_merger_node`,
  `agents/patient_data_aggregator.py` (patient summary),
  `nodes/validation_nodes.py::validation_node`, `utils/utils.py::aggregate_documents`,
  `utils/audit.py`-equivalent patch application (`apply_audit_patches`,
  `map_flat_key_to_patient_summary_path` — in `nodes/audit_nodes.py` / utils).

**Porting rules:** prompts byte-for-byte verbatim (including the JSON-schema-as-text blocks
and persona text) — only replace healthpay's runtime `{{VARS}}`/`` `previous_json` ``
mechanics as described below. Every constant gets a comment header:
`# Source: healthpay-ai@test-fhpl <path> (ported 2026-07-10)`.

### IPD task table (name → deps, type, runtime, schema, gold_feed_keys)

| Task | depends_on | Type | reference_runtime (from source) | Schema | gold_feed_keys (for unselected deps) |
|---|---|---|---|---|---|
| `segregation` | — | doc (full PDF) | gemini-3-flash · thinking_level low | `IpdDocumentSegregatorResponse` (+ post-process `aggregate_documents` port → aggregated_segments dict stored alongside) | — |
| `discharge_summary` | segregation | doc (discharge_summary + consolidated_bill pages) | gemini-3-flash · level minimal | `DischargeSummaryOutput` | ("segregation",) |
| `itemized_bills` | segregation | doc (itemized_bill pages) | gemini-2.5-flash · budget 8000 | `IpdItemizedBillsOutput` (pharmacy bill shape `{bills:[{bill{…,bill_id,bill_type}, items[]}]}`) | ("segregation",) |
| `consolidated_bills` | segregation | doc (consolidated_bill pages) | gemini-2.5-flash · budget 8000 | `IpdConsolidatedBillsOutput` | ("segregation",) |
| `merge_bills` | itemized_bills, consolidated_bills | **deterministic** | — | merged bills dict | ("itemized_bills","consolidated_bills") |
| `items_categorisation` | merge_bills | text | gemini-2.5-flash · budget 8000 | `IpdItemsCategorisationOutput` | ("merge_bills",) — accepts gold `upstream_bills` alias |
| `nme_analysis` | items_categorisation | text | gemini-2.5-flash · budget 8000 | `NMEAnalysisResponse` | ("items_categorisation",) |
| `claim_form` | segregation | doc (claim_forms pages) | gemini-2.5-flash · budget 0 | `IpdClaimFormOutput` | ("segregation",) |
| `identity_document` | segregation, claim_form | doc (identity pages) — instruction templated with `{patient_context}` ← claim_form's patient_name | gemini-2.5-flash · budget 0 | `IdentityDocumentOutput` | ("segregation","claim_form") |
| `cheque_bank` | segregation | doc (cheque_or_bank_details pages) | gemini-3-flash · budget 0 | `BankDetailsOutput` | ("segregation",) |
| `patient_summary` | claim_form, discharge_summary, cheque_bank, identity_document | **deterministic** (port `PatientDataAggregator` to pure function over upstream outputs — NO DB reads) | — | `PatientSummaryData` (4 sections) | its four deps |
| `audit` | nme_analysis, patient_summary, segregation | doc (all pages EXCEPT {other, investigation_report}) — system prompt via ported `get_audit_prompt` filling `{{CLAIMED_AMOUNT}} {{CALCULATED_TOTAL}} {{JSON_OUTPUT}} {{PATIENT_SUMMARY_FIELDS}} {{POLICY_RULES}} {{STAY_ASSESSMENT}}` | **gemini-3.1-pro · thinking_level medium · max_output_tokens 16000** (OPD variant: gemini-3-flash) | `IpdAuditOutput{analysis, patches[], validation}` (typed AuditPatch incl. EDIT_CLAIMED_AMOUNT, EDIT_PATIENT_SUMMARY) | ("nme_analysis","patient_summary","segregation") |
| `validation` | nme_analysis, patient_summary, segregation | **deterministic** (port validation math) | — | `ValidationScores` | its deps |

Variants: `IPD` default (=CL/RM). `variant="PP"` drops `consolidated_bills` (and
merge_bills degrades to itemized-only, as in `FlowConfig`). Do NOT port healthpay's OPD
FlowConfig variant (Colosseum's OPD pack covers OPD), the >50-page split-half segregation
(document as a known limitation; Colosseum sends full PDF — page cap risks noted), the
DB fuzzy categorisation pre-pass (LLM-only; note the difference), or MinIO/store nodes
(Colosseum's RunResult persistence replaces store nodes — "store nodes" are satisfied by
persisting every task's parsed output per run).

**Fidelity tradeoffs to document at the top of `tasks/ipd.py`:**
1. Structured output via Instructor instead of schema-in-prompt + json_repair +
   continuation loop (MAX_CONTINUATIONS=12). Prompts keep their textual schema blocks
   verbatim. The gateway repair ladder substitutes for json_repair. Continuations are NOT
   implemented — if MAX_TOKENS truncation is observed on bills, raise max_output_tokens via
   runtime_overrides.
2. `patient_summary` reads upstream outputs from the run (or gold), not from a DB.
3. `nme_analysis` uses the base NME prompt (insurer-specific injection replaced by a
   `policy_rules` context slot fed from gold/`benefits` when provided).

**Input builders** (`tasks/ipd.py`): mirror `tasks/opd.py::build_text_inputs` style — pure
functions from upstream outputs → instruction context; page-range computation from
segregation output (aggregated_segments doc_type → `"start-end,…"` strings compatible with
`Task.build_input(page_ranges=…)`); audit's claimed_amount/calculated_total computed by
ported `calculate_total_amount_from_nme_analysis` + patient-summary flattening
(`flatten_patient_summary_fields` port).

## Part 2 — OPD parity extension (from superclaims-ai, working tree)

1. Annotate the existing 8 tasks with `depends_on`, `gold_feed_keys`, and
   `reference_runtime` from the TOML runtime blocks (`clients/base/graph/opd.toml` +
   `clients/ekincare/graph/opd.toml`): segregation gemini-3-flash/low/timeout120;
   policy_extraction 2.5-flash/0; itemized+consolidated 2.5-flash/8000;
   items_categorisation 2.5-flash/8000; nme 2.5-flash/8000; benefit_plan 2.5-flash/2048;
   audit gemini-3-flash/low/max_output 16000.
2. Add parity tasks (prompts+schemas from `lang_graph/prompts|schemas` of superclaims-ai,
   verbatim, provenance comments): `claim_form` (deps: segregation), `prescription`
   (segregation), `identity_document` (segregation, claim_form — note: in superclaims it
   depends only on segregation pages but runs after claim_form; keep deps (segregation,)),
   `cheque_bank` (segregation), `extract_icd_codes` (prescription, merge_bills),
   `patient_summary` (deterministic port of `utils/patient_data.py::PatientDataAggregator`;
   deps claim_form, prescription, merge_bills, cheque_bank, identity_document). Wire
   benefit_plan's optional clinical context from prescription when selected.
3. Update `OPD_PIPE_ORDER` to a valid topological order including new tasks; existing
   runners must keep working (order only appends/inserts, names unchanged).

## Part 3 — Gold format extension

- Any task name in either pack is now a legal key under `gold["tasks"]` and usable as an
  upstream feed. Keep legacy aliases working: `upstream_bills` → `merge_bills`,
  `upstream_benefits` → benefit context.
- New non-scored feed-only keys (add to `NON_SCORED_TASKS` in `scoring/report.py`):
  `upstream_bills`, `upstream_benefits`, `claimed_amount`, `policy`, `benefits`,
  `patient_name` — plus any task key present in gold but NOT in the run's selected tasks is
  simply unused for scoring (already the behavior; add a test).
- `docs/ground-truth-format.md`: document per-pack feedable keys and the exact JSON shape
  each expects (= the task's output schema; for segregation the aggregated_segments shape
  too). Update `scripts/convert_gold_exports.py` only if the CSV importer needs new columns
  (optional).

## Acceptance criteria

1. `get_task_pack("IPD")` returns the pack; `resolve_subset(["segregation","audit"],
   "gold")` yields audit gold-requirements {nme_analysis, patient_summary, segregation}
   (minus whichever are selected); PP variant drops consolidated_bills.
2. Prompt-diff test: for each ported prompt constant, a checksum test against
   `git show test-fhpl:<path>` extraction (or a frozen fixture) proves verbatim port.
3. Deterministic transforms unit-tested against fixtures captured from the reference logic
   (build small input JSONs by hand from the schemas; patient_summary + merge_bills +
   validation produce the expected shapes).
4. Audit prompt builder fills all six `{{VARS}}`; golden-file test for a sample context.
5. Every task exposes `reference_runtime` matching the tables above (asserted in tests).
6. OPD existing tests (`backend/tests/test_opd_tasks.py`) still green; new
   `test_ipd_tasks.py` + `test_opd_parity.py` green; ruff clean.
7. Live smoke (creds required): 1 test-doc IPD run of segregation+itemized_bills on
   `gemini-2.5-flash-lite` through the engine (or `runner/opd_smoke.py`-equivalent CLI you
   add as `runner/ipd_smoke.py`) produces valid parsed outputs.

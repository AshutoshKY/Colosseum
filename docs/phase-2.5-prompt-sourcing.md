# Phase 2.5 — Corrected prompt sourcing + finish the OPD pipeline (must be fully working)

> Supersedes the prompt-sourcing in [phase-2-opd-and-models.md](./phase-2-opd-and-models.md)
> for these specific agents. Phase 2 vendored prompts from superclaims-ai; the user wants the
> sources below instead. Earlier phases committed at `a8b4b5d`; Phase 2 work is uncommitted in
> the working tree (catalog YAMLs, OPD tasks, scoring, observability, opd_smoke).

## Corrected source of truth per agent (use FULL prompts — do not drop a single line)

Vendor these **from healthpay-ai** (`/Users/ekincare/superclaims/healthpay-ai/healthpay/backend/app/lang_graph/`):

| Task | Prompt source (healthpay-ai) | Schema / model source | Agent logic ref |
|---|---|---|---|
| segregation | `prompts/` (file segregation prompt — check `prompts.py` / `structured_data_extractors.py`) | `models/document_segregator.py` | `agents/file_segregation_agent.py` |
| itemized_bills | `prompts/bills.py` + `prompts/bill_prompt_blocks.py` + `prompts/consolidated_prompt_block.py` | `models/pharmacy_bill.py` | `agents/pharmacy_bills_agent.py` |
| items_categorisation | `prompts/` (items categorisation prompt) | item-category models (`models/llm_input_models.py` / repo `item_category_mapping`) | `agents/items_categorisation.py` |
| nme | `prompts/nme.py` + `utils/nme_prompt_builder.py` | `models/nme_analysis.py` | `nodes/nme_analysis_nodes.py` |
| audit | `prompts/audit.py` | audit schema (find in `models/` / `prompts/schema/`) | `nodes/audit_nodes.py` (keep continuation/degenerate fallback) |

Vendor **from superclaims-ai** (`/Users/ekincare/superclaims/superclaims-ai/backend/app/lang_graph/`):

| Task | Prompt source | Schema source | Agent logic ref |
|---|---|---|---|
| benefit_plan | `prompts/ekincare.py` (ekincare.benefit_plan) | `schemas/adjudication.py` → `BenefitPlanOutput` | `agents/benefit_plan.py` |

**Rules:**
- Copy each prompt **verbatim and complete** — every block, example, and instruction line. If a
  prompt is assembled from blocks/builders (e.g. `bill_prompt_blocks.py`, `nme_prompt_builder.py`),
  reproduce the fully-assembled prompt. De-tune ONLY provider-specific phrasing (literal
  "Gemini"/"Vertex"/PDF-file mechanics) so it is model-neutral — keep all task logic, fields,
  examples, and classification rules.
- Structured output stays **mandatory** (Pydantic schema vendored faithfully; field names,
  aliases, enums, defaults preserved). Reconcile with whatever Phase 2 already created under
  `backend/app/tasks/schemas/` and `tasks/prompts/` — replace superclaims-sourced prompts with
  the healthpay-sourced ones above, don't keep duplicates.

## Wiring / piping / classification (make it real, not stubs)

- Each task = prompt + schema + input builder + doc-type filter, registered in the OPD task
  pack with the correct **pipe order**: segregation → (policy_extraction) → itemized_bills →
  items_categorisation → nme → benefit_plan → audit. Where a downstream task consumes an
  upstream task's structured output (items_categorisation consumes merged bills; nme consumes
  categorised items; audit consumes the assembled JSON), wire that data flow explicitly so a
  document can flow end-to-end through the OPD pack for one model.
- Keep the segmentation/classification mapping (document_type → which task consumes which
  segment) faithful to the source projects.

## Credentials (already set up — just use them)

`Colosseum/.env` is configured (gitignored) with `EXTERNAL_ENV_FILES` → superclaims-ai/healthpay-ai
`.env`, `GOOGLE_APPLICATION_CREDENTIALS=Colosseum/secrets/vertex-sa.json` (gitignored),
`VERTEXAI_PROJECT=vertex-internal-testing`, Langfuse keys. `get_settings().has_vertex_credentials`
returns True. Do NOT print, move, or commit these secrets.

## Definition of done (everything must actually work)

1. `pytest -m "not live"` green; `ruff` clean; `alembic upgrade head` clean.
2. **Live OPD e2e on real docs**: run the full OPD task pack on **2–3 PDFs from `test-docs/`**
   with Gemini, piping each task's output into the next, and **persist every detail** — prompt,
   structured input, raw + parsed output, tokens (input/output/thinking/cached), cost, latency,
   retries — in the DB. Then run the same on **each Model Garden model verified callable on the
   project** so outputs are comparable.
3. **Comparisons work**: the scoreboard ranks models per task by composite (accuracy where
   ground truth exists, else validity + cost + latency); side-by-side outputs retrievable.
4. Capability gates hold (text-only models skipped for image/PDF tasks, recorded "not applicable").
5. Full 27-PDF × all-models matrix stays behind an explicit command (cost control) — do not
   auto-run it.
6. Commit the work. Report: which prompts came from where (with line counts to prove fullness),
   what ran live (models × docs × tokens/cost/latency), test output, and exact run commands.
```

# Colosseum — Phase 2 Plan & Tasks: OPD Task Pack + Full Model Garden Catalog

> Builds on Phase 1 (provider core + itemized_bills vertical slice; commit `a8b4b5d`).
> Companion docs: [plan.md](./plan.md), [project-overview.md](./project-overview.md),
> [models-and-caveats.md](./models-and-caveats.md).

## Goal of Phase 2

1. **Expand the model catalog to ALL Vertex AI Model Garden models and ALL versions** —
   every family, every version, every variant (thinking / non-thinking / mini / lite / vision):
   Gemini, Grok (4.2 / 4.3 / thinking + non-thinking), Qwen (all), Kimi (all), DeepSeek (all),
   Gemma (all), GLM (all), plus Claude / Mistral / Llama / gpt-oss as present. **No version
   left out.**
2. **Build the OPD task pack** (claim_type = `OPD`) — mirror how `superclaims-ai`/`healthpay-ai`
   process OPD claims, as model-neutral, mandatory-structured-output tasks.
3. **Focus on OPD first.** Add **IPD placeholders** for its two sub-types — **CL (cashless)**
   and **RM (reimbursement)** — scaffolded but not built out yet.
4. **Make everything run and be tested** — offline tests green + a real test-run on the OPD
   PDFs the user dropped in `Colosseum/test-docs/` (27 OPD claim PDFs).
5. **Ground-truth / baseline hook** — wire ingestion so the user's baseline adjudication data
   (provided later) scores accuracy/precision/recall via the existing field-metrics.

## Claim-type model (confirmed from superclaims-ai)

From `superclaims-ai/.../lang_graph/constants.py`:
`DEFAULT_CLAIM_TYPE_BY_PROJECT = {"ekincare": "OPD"}`,
`CLAIM_TYPE_ALIASES = {"IPD": "CL", "MR": "RM"}`.
So: **OPD** is its own claim type; **IPD** resolves to **CL (cashless)** and **RM
(reimbursement)** profiles. Profiles live at
`superclaims-ai/.../lang_graph/config/profiles/base/{opd,cl,rm,pp}.toml` and the ekincare
overlay at `clients/ekincare/opd.toml`.

### OPD pipeline = the agents to vendor (from `base/opd.toml` + `ekincare/opd.toml`)

LLM agents, in dependency order (model_key + thinking shown as the production reference):
1. `segregation` — gemini_3_flash, thinking LOW
2. `policy_extraction` (ekincare) — gemini_2_5_flash
3. `claim_form` — gemini_2_5_flash
4. `prescription` — gemini_2_5_flash
5. `itemized_bills` — gemini_2_5_flash, thinking 8000  **(done in Phase 1)**
6. `consolidated_bills` — gemini_2_5_flash, thinking 8000
7. `cheque_bank` (optional), `identity_document` (optional) — gemini_2_5_flash
8. `items_categorisation` — gemini_2_5_flash, thinking 8000 (text agent: consumes merged bills)
9. `nme_analysis` — gemini_2_5_flash, thinking 8000
10. `benefit_plan` (ekincare) — gemini_2_5_flash, thinking 2048
11. `audit` — gemini_3_flash, thinking LOW (has the degenerate-output fallback ladder)

Non-LLM steps (`store_*`, `merge_bills`, `build_patient_summary`, `validation`,
`fwa_invoice_duplicate`, `completion`) are orchestration — Colosseum models each LLM agent as
an independent **task** (own prompt + schema), plus a `merge_bills` text transform. The
benchmark runs each task independently across models (we are comparing per-task model quality,
not running the full graph end-to-end yet).

**Priority subset for this phase** (the user's stated focus): `segregation`,
`itemized_bills` (done), `consolidated_bills` + `merge_bills`, `items_categorisation`,
`nme_analysis`, `audit`, `benefit_plan`, `policy_extraction`. Vendor schemas as-is; de-tune
prompts to be model-neutral (strip Gemini/Vertex/PDF-specific wording; keep task logic +
mandatory structured output). Sources:
`superclaims-ai/.../lang_graph/{agents,prompts,schemas}/`.

## Model catalog: requirements (the big one)

Produce an **exhaustive, versioned registry** that feeds
`backend/app/providers/registry.py` and is documented in `docs/models-and-caveats.md`.

- **Enumerate authoritatively.** Use current sources: Vertex AI Model Garden model list
  (`gcloud ai model-garden models list` if the CLI/creds are available), the Vertex partner /
  MaaS docs, and LiteLLM's `vertex_ai` / `vertex_partner` provider model lists. Web-verify
  versions for each family. Capture **every version and variant**, including thinking vs
  non-thinking modes where the same family exposes both.
- **Structure**: a data-driven catalog (e.g. `providers/catalog/*.yaml` or a generated
  module) keyed by `model_id`, grouped by `family` → `version` → `variant`, each carrying the
  full `ModelCapability` profile (access pattern, modalities, pdf_native, vision,
  max_image_mb / max_payload_mb / megapixels / image_formats, context_window,
  structured_method, thinking, caching, batch, pricing_ref) **and caveats**.
- **Availability gating.** A model is `enabled=True` **only if verified callable** on this
  project's Vertex (or has a working external key). Everything else is registered
  `enabled=False, verified=False` with a `reason` (e.g. "not enabled on project",
  "no API key", "needs self-deploy endpoint"). **Do not ship unverified capability flags.**
- **External vs Vertex.** Models in Vertex Model Garden → route via `vertex_partner` using the
  existing Vertex creds. Models only on external APIs (e.g. some GLM/Kimi/Grok endpoints if not
  in this project's Model Garden) → register under `openai_compatible`/`xai` providers,
  `enabled=False` until a key is supplied (we only have Gemini/Vertex + Langfuse creds now).
- **Pricing** for each: extend the rate card (`providers/pricing/`) with input/output/cache/
  thinking $ per 1M; mark unknowns and `pricing_version`. Self-deploy models are VM-uptime
  priced — flag separately.
- **Thinking/non-thinking variants** must be first-class: where a model supports a reasoning
  budget/level, expose both a thinking config and a non-thinking config so the benchmark can
  compare cost/accuracy of each.

## Credentials (read from existing `.env` — never hardcode/commit)

Resolve via `EXTERNAL_ENV_FILES` (the Phase 1 pattern). Use
`/Users/ekincare/superclaims/superclaims-ai/.env` (has inline
`GOOGLE_CLOUD_CREDENTIALS_JSON`, `SUPERCLAIMS_GOOGLE_PROJECT_ID=vertex-internal-testing`,
`GOOGLE_API_KEY`, and `LANGFUSE_*` keys) and/or `healthpay-ai/.env`. **Wire Langfuse** tracing
(keys are present). Treat all real secret values as untrusted input — reference by env var,
keep only `.env.example` in git.

## IPD placeholders (scaffold only)

Add claim-type scaffolding for `IPD` with sub-types `CL` (cashless) and `RM` (reimbursement):
profile/registry entries + empty task-pack stubs that raise "not implemented yet". Mirror the
shape of `base/cl.toml` and `base/rm.toml` for later. **Do not build OPD-equivalent logic for
them in this phase.**

## Ground-truth / baseline hook

The user will provide baseline adjudication data. Add an importer
(`scoring/ground_truth_import.py` + a CLI) that loads per-document, per-task gold JSON into the
`ground_truth` table, so `field_metrics.py` produces accuracy/precision/recall and the
scoreboard can rank correctness. Document the expected baseline format in
`docs/ground-truth-format.md` so the user knows what to hand over.

## Test-run requirement ("make sure everything runs")

- Offline: full `pytest -m "not live"` green; `ruff` clean; alembic upgrade clean.
- Live OPD smoke (cost-controlled): run the priority OPD tasks on **2–3 PDFs from
  `test-docs/`** with **Gemini first**, then with **each Model Garden model verified callable
  on the project**. Persist full `run_result` rows (tokens incl. thinking/cache, cost,
  latency, parsed output). Confirm the scoreboard ranks models by composite (accuracy where
  ground truth exists, else validity + cost + latency).
- The **full** 27-PDF × all-models matrix is a **user-triggered** run, not automatic — keep it
  behind an explicit command to control spend.
- Capability gates must hold: text-only models (e.g. DeepSeek R1) are skipped for image/PDF
  tasks and recorded as "not applicable", not failed.

## Task checklist (for the build agent)

- [ ] Read Phase 1 code + all `docs/` + the OPD profiles/agents/prompts/schemas in superclaims-ai.
- [ ] Vendor + de-tune OPD priority tasks (segregation, consolidated_bills, merge_bills,
      items_categorisation, nme_analysis, audit, benefit_plan, policy_extraction) with
      mandatory Pydantic schemas. Reuse the audit free-text→JSON-repair ladder.
- [ ] Build the exhaustive, versioned model catalog (all families/versions/variants,
      thinking + non-thinking) → `registry.py` + `docs/models-and-caveats.md`; gate `enabled`
      by live verification; extend pricing.
- [ ] Add `vertex_partner` + `openai_compatible`/`xai` adapters; reuse `pdf_to_images` +
      size guards; wire Langfuse.
- [ ] Add claim-type layer: OPD task pack wired; IPD (CL, RM) placeholders.
- [ ] Ground-truth importer + `docs/ground-truth-format.md`.
- [ ] Tests: offline green + cost-controlled live OPD smoke on `test-docs/`. Paste output.
- [ ] Report: catalog summary (counts by family/enabled), what ran, what's gated off and why,
      exact commands. Do NOT run the full matrix automatically.
```

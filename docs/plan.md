# Colosseum — Model-Agnostic LLM Benchmark Platform (Build Plan)

> This is the approved build plan. Companion docs: [project-overview.md](./project-overview.md)
> (goal + context) and [models-and-caveats.md](./models-and-caveats.md) (model catalog).

## Context

`superclaims-ai` and `healthpay-ai` run a fixed pipeline of claim-processing agents
(segregation, itemized bills, items categorisation, NME, audit, benefit plan, policy)
**hard-wired to Gemini on Vertex AI** via `langchain_google_genai`
(see `superclaims-ai/backend/app/lang_graph/llm/client.py` — model resolution is a
Gemini-only `if/elif`, and every agent calls `get_chat_model(...)` returning a
`ChatGoogleGenerativeAI`).

We want **Colosseum**: a sibling project that runs the *same* prompts, *same* sample
documents, and *same* mandatory structured-output schemas across *many* models/providers
(Gemini Vertex + Model Garden first; then Grok, Qwen, GLM, DeepSeek, Kimi, Gemma…) so we
can pick the most **cost-efficient** model per task. It must be plug-and-play: add a model
+ provider, and it just runs — capturing every input/output, all token classes
(input/output/thinking/cache), latency, cost, and the structured response, then comparing
**accuracy + confidence + performance + cost** with an unbiased multi-signal scorer.

The hard problem is **per-model caveats** (verified during research):
- **Grok vision API**: base64 images capped at **4 MB** (20 MB via URL), jpg/png only,
  ~33 MP, tile-based image token billing → PDFs must be rasterized to images per page.
- **Gemini**: ingests PDF natively (current code sends `{"type":"file","mime_type":"application/pdf","base64":...}`).
- Structured-output reliability **varies per model** — some need json_schema, some json
  mode + repair, some tool-calling. So a capability/validation layer is required regardless
  of transport library.

## Decisions (confirmed with user)

- **Transport**: LiteLLM (unified transport + cost) + **Instructor** (Pydantic structured
  output w/ retries) + our own **capability/adapter layer** for caveats. **LangGraph** for
  per-task orchestration/state/tracing. Start with **Gemini Vertex AI + Vertex Model Garden**;
  reuse API keys from `superclaims-ai/.env` & `healthpay-ai/.env`; wire **Langfuse**.
- **Infra**: Full-stack but right-sized. **Postgres + SQLModel** (store everything),
  **FastAPI** backend, **lightweight Vite/React dashboard** (input/output/scoreboard).
  **Temporal**: include as the batch orchestrator *but* behind an orchestrator-agnostic
  runner so local dev works on plain asyncio (defer standing up Temporal to Phase 2).
  **Redis**: yes, minimal — response cache/dedup + rate-limit coordination only.
  **RAG**: **not needed for audit/bills**; defer until a retrieval-dependent agent (policy/
  benefit) is ported.
- **Task pack v1**: vendor **audit** + **itemized bills** agents from `superclaims-ai`,
  keep the **core task instructions + mandatory structured-output schemas**, but **de-tune**
  the Gemini/Vertex-specific wording so prompts are model-neutral.
- **Scoring**: multi-signal — deterministic field metrics (vs ground truth where available)
  + LLM-as-judge (neutral strong model, rubric) + cost/latency/token efficiency → composite
  scoreboard.

## Document conversion / compression / merging (must work correctly + be tested)

Caveats above mean the adapter layer needs a robust, tested document-prep toolkit. Required,
with chosen libraries:
- **PDF split / select pages / merge**: `pypdf` (extend existing `extract_pages_as_base64`
  with `merge_pdfs()` and `select_pages()`); for several source docs per claim, merge into one
  packet or feed per-segment.
- **PDF → image rasterization** (non-PDF-native providers): `pymupdf` (PyMuPDF / fitz) primary
  (no system deps), `pdfium2` fallback; render at a target DPI.
- **Image compression / resize to hit caps**: `Pillow` — iterative downscale + quality step to
  bring each image under the per-model cap (e.g. Grok 4 MB base64, Vertex 30 MB total), convert
  to jpg/png as the model requires, cap resolution (≤33 MP for Grok).
- **Payload-size accounting**: measure **base64-encoded** byte size (not raw) since that's what
  the API counts; page-split or compress until under cap; record original vs sent size.
- **Tests are mandatory** (fills the "capability gaps" requirement): golden tests that a known
  PDF → images stays under each provider's cap, that page selection/merge round-trips, that an
  oversized image is compressed under the limit, and that mime/format conversions are correct.

## Architecture

```
colosseum/
  backend/
    app/
      core/            config (pydantic-settings), env loading, logging
      models/          SQLModel tables (see Data model below)
      db/              engine, session, migrations (alembic)
      providers/       <-- the model-agnostic core
        gateway.py     ModelGateway: chat() + structured() unified entrypoint
        registry.py    model registry (id, provider, capabilities, pricing ref)
        capabilities.py ModelCapability profile (vision, pdf_native, max_image_mb,
                        thinking, cache, structured_method)
        adapters/      per-provider input normalization (pdf->image, size guard)
          base.py, gemini_vertex.py, openai_compat.py (grok/qwen/glm/deepseek/kimi),
          model_garden.py
        usage.py       normalize token usage across providers -> canonical fields
        pricing/       rate_card.json (extend existing vertex card) + cost estimator
      tasks/           the "task pack" (model-neutral, vendored)
        base.py        Task protocol: prompt, schema, input builder, doc-type filter
        audit.py, itemized_bills.py
        prompts/       de-tuned audit.py, bills.py
        schemas/       audit.py, bills.py (vendored Pydantic, mandatory)
      runner/
        matrix.py      expand (task x document x model x config) -> run cells
        executor.py    asyncio executor (Phase 1) calling gateway per cell
        temporal/      workflow + activities wrapping the same executor (Phase 2)
      scoring/
        field_metrics.py   schema-aware diff: precision/recall/field accuracy
        judge.py           LLM-as-judge (rubric, neutral model, pairwise+absolute)
        scoreboard.py      composite ranking incl. cost/latency/tokens
      api/             FastAPI routers: runs, models, scoreboard, documents
      observability/   Langfuse wiring for litellm + langchain
    tests/
    alembic/
  frontend/            Vite + React dashboard (runs list, side-by-side outputs, scoreboard)
  data/                sample claim PDFs (copied from healthpay-ai)
  docs/                this folder (plan + overview + model catalog)
  docker-compose.yml   postgres + redis (+ temporal in Phase 2)
  .env.example
  pyproject.toml
```

### Provider core (the plug-and-play seam)

`ModelGateway.structured(model_id, system, user_content, schema, *, config)`:
1. Look up `ModelCapability` from `registry.py`.
2. Run the provider **adapter** to normalize `user_content`:
   - PDF + `pdf_native` → pass through as file part (Gemini path).
   - PDF + `not pdf_native` → rasterize pages to PNG/JPEG via `pymupdf`/`pdfium2`,
     enforce `max_image_mb` (downscale/split), attach as image parts.
   - guard image size/count/resolution per capability (Grok 4 MB rule, etc.).
3. Call **Instructor-over-LiteLLM** with the Pydantic `schema`
   (`response_model=schema`, automatic retries/validation), `structured_method` chosen by
   capability (json_schema | json_mode | tools). Mirrors the existing
   `ainvoke_structured(...)` contract but provider-agnostic.
4. Normalize usage via `usage.py` into canonical token fields and estimate cost via
   `pricing/`. Persist a `RunResult` row.

**Why both LangGraph and LiteLLM:** LangGraph defines each task as a small graph (matches
superclaims-ai patterns, room to grow to multi-node agents + lets Langfuse trace state);
the *model binding inside nodes* goes through `ModelGateway` (Instructor+LiteLLM) instead of
`ChatGoogleGenerativeAI`, which is what makes it provider-agnostic. We do **not** rely on
`.with_structured_output` (reliability varies across providers) — Instructor handles that.

### Data model (Postgres / SQLModel) — "store everything"

- `model_catalog`: model_id, provider, display_name, capabilities (JSON), enabled.
- `pricing_rate` (or JSON rate card + version): input/output/cache/thinking $/1M, version.
- `document_sample`: id, path, claim_type, page_count, sha256.
- `benchmark_run`: id, name, task_pack version, created_at, status (the batch).
- `run_cell`: run_id, task, document_id, model_id, config (thinking/temp), status.
- `run_result`: cell_id, raw_response (JSON), parsed_output (JSON), valid (bool),
  input_tokens, output_tokens, thinking_tokens, cached_tokens, total_tokens,
  est_input_cost/output_cost/cache_cost/total_cost_usd, latency_ms, retries,
  error (JSON), usage_raw (JSON). Extends existing `LLMCallLog`
  (`superclaims-ai/.../models/llm_call_log.py`) with thinking + parsed_output + latency.
- `score`: result_id (or cell pair), field_metrics (JSON), judge_score (JSON),
  composite (Numeric), rank.
- `ground_truth` (optional): document_id + task → labeled gold JSON for field metrics.

### Scoring (multi-signal)

- **field_metrics.py**: walk the task's Pydantic schema; compute per-field exact/normalized
  match, list precision/recall (e.g. bill line items), numeric tolerance for amounts; emit
  overall accuracy when ground truth exists, else structural validity + self-consistency.
- **judge.py**: neutral strong judge model (configurable, e.g. a Gemini/Claude not under
  test) scores each output against a rubric (faithfulness to document, completeness,
  no-hallucination) — absolute 1–5 + pairwise; randomize order to de-bias; never let a model
  judge itself.
- **scoreboard.py**: composite = weighted(accuracy, judge, 1/cost, 1/latency); per-task and
  per-document leaderboards; surfaces "cheapest model above accuracy threshold".

## Files to reuse / vendor (with paths)

- Vendor + de-tune prompts from
  `superclaims-ai/backend/app/lang_graph/prompts/audit.py` (1303 lines) and `prompts/bills.py`
  (ITEMIZED_BILLS_SYSTEM_PROMPT). Strip Gemini/Vertex-specific phrasing; keep task logic.
- Vendor schemas **as-is** (already model-neutral Pydantic):
  `schemas/bills.py` → `ItemizedBillsOutput`, `ItemizedBillGroup`, `ItemizedBillItem`,
  `BillHeader`, `FacilityDetails`; `schemas/adjudication.py` → `AuditAnalysisOutput` (+ nested
  `AuditMedicalLegibility`, `AuditPolicyViolation`, `AuditIcdCode`, `AuditPatch`,
  `AuditValidation`).
- Reuse pricing approach + the rate card values from
  `superclaims-ai/.../lang_graph/pricing/vertex_rate_card.json` and the cost estimator in
  `pricing/estimated_vertex_cost.py` (extend to multi-provider + thinking tokens).
- Reuse PDF page-extraction logic from `lang_graph/utils/pdf.py` (`extract_pages_as_base64`);
  add a `pdf_to_images()` sibling for non-PDF-native providers.
- Sample documents: copy the claim PDFs in `healthpay-ai/` (e.g. `02B-2026-006427.pdf`,
  `02C-2026-004731.pdf`) into `colosseum/data/`.
- Keep the `audit.py` **degenerate-output fallback** idea (free-text → JSON repair) as a
  provider-agnostic reliability ladder in the gateway, since weaker models will need it.

## Build phases

0. **Docs first** *(this folder — done)*: `plan.md`, `project-overview.md`,
   `models-and-caveats.md`. The build agent verifies every "verify" capability cell live
   against current provider docs before finalizing the registry.
1. **Scaffold + provider core (vertical slice)**: pyproject, config/env (load existing
   `.env`), Postgres+SQLModel models, `ModelGateway` + capability registry (generated to match
   `models-and-caveats.md`) + Gemini-Vertex adapter + Instructor/LiteLLM structured call +
   usage/pricing. **Document-prep toolkit (pypdf/pymupdf/pdfium2/Pillow) with its golden
   tests built here.** Prove: run **itemized_bills** on one PDF with **one Gemini model**,
   persist a full `run_result`.
2. **Task pack + multi-model**: vendor/de-tune audit + itemized_bills prompts & schemas;
   add openai-compat adapter (Grok/Qwen/GLM/DeepSeek/Kimi) + Vertex Model Garden (`vertex_partner`)
   + `pdf_to_images` with per-model size guards (4 MB Grok, 30 MB Vertex). Run the matrix
   across ≥2 providers; skip image tasks for text-only models (DeepSeek R1) via capability gate.
3. **Scoring + scoreboard**: field metrics + LLM judge + composite ranking; ground-truth
   ingestion.
4. **Orchestration + UX**: Temporal workflow wrapping the executor; Langfuse traces;
   FastAPI + Vite dashboard (runs, side-by-side outputs, cost/accuracy leaderboard); Redis
   response cache.

## Verification

- **Document-prep golden tests (capability-gap coverage)**: known PDF → images stays under
  each provider's cap; page select/merge round-trips; oversized image compresses under the
  4 MB (Grok) / 30 MB (Vertex) limit; mime/format conversion (jpg/png) is correct; base64
  size accounting matches what the API counts.
- **Unit**: capability adapter tests (PDF→image size guard hits Grok's 4 MB limit; Gemini
  passes PDF through; text-only model is gated out of image tasks); usage normalization
  across mocked provider payloads; field-metrics on a known output vs gold.
- **Integration (Gemini, real key)**: run itemized_bills + audit on a sample `data/*.pdf`
  with one Gemini model; assert a valid `AuditAnalysisOutput`/`ItemizedBillsOutput` persisted
  with non-zero token + cost fields.
- **Cross-model smoke**: same task/doc across 2 providers; confirm both rows persist and the
  scoreboard ranks them by composite (accuracy/cost/latency).
- **E2E**: `docker-compose up` (postgres+redis) → trigger a `benchmark_run` via API →
  dashboard shows side-by-side outputs + leaderboard → Langfuse shows traces.
- Quick check that the cheapest-model-above-threshold query returns the expected model on a
  seeded dataset.

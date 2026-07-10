# 01 — Context: Colosseum Current Architecture (as of 2026-07-10)

> Self-contained current-state report of `/Users/ekincare/superclaims/Colosseum`.
> Read together with `00-master-plan.md`. Line numbers are approximate anchors — verify
> before editing.

## 1. What it is

Model-agnostic LLM benchmarking platform for health-insurance claims processing. Runs the
same prompts + mandatory structured-output schemas across many LLMs/providers on real claim
PDFs, then compares accuracy/cost/latency. ~9,160 lines of Python. Git history is only 2
commits (scaffold + one squash), so treat the working tree as the source of truth, not
history.

**Reality vs. docs:** `docs/plan.md` describes FastAPI + React + LangGraph + Temporal +
Redis + LLM-judge. Almost none of that orchestration/API surface was built. What exists:
provider gateway, YAML model catalog, an 8-task OPD pipeline, deterministic field-metric
scoring, SQLModel persistence, and one Streamlit app as the de-facto UI/runner.

## 2. Backend layout (`backend/app/`)

| Package | Contents |
|---|---|
| `core/` | `config.py` (pydantic-settings; layers sibling repos' `.env` via `EXTERNAL_ENV_FILES` — external files < Colosseum `.env` < process env), `logging.py` |
| `db/` | `engine.py` — sync SQLModel engine, `session_scope()` contextmanager; Postgres `localhost:5433` (docker-compose), SQLite in tests |
| `models/` | SQLModel ORM tables (§4) |
| `providers/` | gateway, registry, capabilities, `catalog/*.yaml`, adapters, pricing, docprep, usage (§3) |
| `tasks/` | task protocol + OPD pack + prompts + schemas + claim_types (§5) |
| `runner/` | `opd_smoke.py` (CLI runner), `persistence.py`, `vertical_slice.py` |
| `scoring/` | `field_metrics.py`, `scoreboard.py`, `report.py`, `ground_truth_import.py` (§6) |
| `observability/` | Langfuse v4 wiring |
| `utils/pdf.py` | page extraction |

**API surface: NONE.** No `backend/app/api/`, zero FastAPI/APIRouter usage anywhere.
Entrypoints: `python -m app.runner.opd_smoke`, `python -m app.scoring.report`,
`python -m app.scoring.ground_truth_import`, and `streamlit run streamlit_app.py`.

## 3. Provider layer (`backend/app/providers/`) — REUSE AS-IS

### 3.1 `gateway.py` — `ModelGateway.structured()` (async, ~line 77)

The single model-agnostic entrypoint. Flow (lines ~90–190):
1. `get_capability(model_id)` → capability profile.
2. `get_adapter(capability).normalize(...)` — **capability gate**: raises
   `CapabilityGateError` for e.g. text-only models on document tasks → recorded as
   `skipped` (not failed) (lines ~111–126).
3. `_call_with_fallback` (~:193) — **Tier 1**: Instructor-over-LiteLLM structured call.
   **Tier 2** repair ladder (free-text gen → `_repair_to_schema` regex/brace extraction →
   schema validation), but only if `capability.needs_repair_fallback` (~:216). Strong models
   surface errors instead of guessing.
4. Usage normalized (`usage.py`) + cost estimated (`pricing/estimator.py`) → `GatewayResult`
   (raw response, parsed output, valid flag, token classes incl. thinking/cached, costs,
   latency, retries, structured_method, endpoint).

Structured method per capability: `json_schema | json_mode | tools` (`_MODE_BY_METHOD` ~:45);
Vertex json_mode uses Instructor `MD_JSON` (~:261). `_provider_kwargs` (~:308) injects
Vertex SA creds / xAI key / openai-compatible `base_url` / thinking budget when supported.
**WS B adds the `bedrock` branch here.**

### 3.2 `capabilities.py`

Frozen pydantic `ModelCapability`: modalities, `pdf_native`, `vision`, size caps
(`max_image_mb`, `max_payload_mb`, `max_image_megapixels`), `structured_method`,
`needs_repair_fallback`, `thinking`, `caching`, `batch`, `pricing_ref`, `enabled`,
`verified`. **Providers enum: `vertex_ai`, `vertex_partner`, `xai`, `openai_compatible`** —
no `bedrock` yet.

### 3.3 `registry.py` + `catalog/*.yaml`

Loads all catalog YAMLs into a module-level `registry` dict at import. Helpers:
`list_models(enabled_only=…)`, `families()`, `catalog_summary()`, `gate_reason()`.
10 YAMLs / 77 models / ~7 enabled:
- `gemini.yaml` — enabled: gemini-2.5-flash / pro / flash-lite. **All Gemini 3.x entries
  gated off** (Vertex 404 on the project previously tried).
- `qwen.yaml` — enabled (text-only): qwen3-235b-instruct, qwen3-coder-480b,
  qwen3-next-80b instruct+thinking.
- `deepseek.yaml` — deepseek-r1-0528 enabled (text-only).
- `open_models.yaml` — gemma-4-26b enabled.
- `claude.yaml`, `grok.yaml`, `glm.yaml`, `kimi.yaml`, `mistral.yaml`, `llama.yaml` — all
  gated (no verified access/keys). Bedrock may unlock some Claude/Llama/Mistral access.

### 3.4 Adapters (`providers/adapters/`)

`base.py`: shared capability `gate()` (~:60) + `get_adapter()` (~:108) selection:
`pdf_native` → `GeminiVertexAdapter` (PDF pass-through); `vision` → `RasterizingAdapter`
(PDF→images within size caps); else `TextOnlyAdapter`. `DocumentInput(path, page_ranges,
mime_type)` is the doc descriptor. `docprep.py` + `utils/pdf.py` do page
extraction/rasterization. **Qwen3-VL-8B uses RasterizingAdapter unchanged.**

### 3.5 Pricing

`providers/pricing/rate_card.json` + `estimator.py`, keyed by `pricing_ref`;
`pricing_version` recorded per run; self-deployed models flagged VM-uptime (rate 0).

## 4. DB models (`backend/app/models/`) + persistence

- `benchmark.py` — `BenchmarkRun(id, name, task_pack_version, status)` (~:26);
  `RunCell(run_id, task, document_id, model_id, config…, status, skip_reason)` (~:36) — one
  task×document×model coordinate; `RunResult` (~:52) — the store-everything row:
  `prompt_system`, `prompt_instruction`, `raw_response`, `parsed_output`, `valid`, token
  counts (input/output/**thinking**/cached/total), 5 cost columns, `latency_ms`, `retries`,
  `error`, `usage_raw`, `structured_method`, `endpoint`.
- `document.py` — `DocumentSample(path, claim_type, page_count, sha256 unique)`.
- `ground_truth.py` — `GroundTruth(document_id, task, gold JSONB)` unique per (document, task).
- `score.py` — `Score(result_id, field_metrics JSON, judge_score JSON ← UNUSED placeholder,
  composite, rank)`.
- `catalog.py` — `ModelCatalog` table exists but live registry loads from YAML, not DB.

Alembic: `0001_initial` emits schema from `SQLModel.metadata`; `0002_run_result_prompt_input`
adds prompt columns. Metadata-driven — new tables just need models imported in `alembic/env.py`.

Persistence: `runner/persistence.py` — `register_document()` (idempotent by sha256),
`persist_cell_result()` (maps `GatewayResult` → `RunResult`, sets cell status
skipped/succeeded/failed).

## 5. Task layer (`backend/app/tasks/`)

### 5.1 Protocol (`tasks/base.py`, current — WS A extends, see master §6.2)

```python
@dataclass(frozen=True)
class Task:
    name: str
    system_prompt: str
    instruction: str
    schema: type[BaseModel]
    requires_documents: bool = True
    default_page_ranges: str | None = None
    document_types: frozenset[str] = frozenset()
    is_text_task: bool = False
    def build_input(self, document_path, *, page_ranges=None) -> TaskInput  # → [DocumentInput]
    def render_instruction(self, **context) -> str  # str.format on instruction template
```

### 5.2 OPD pack (`tasks/opd.py`)

`OPD_TASKS` (~:307), pipeline order `OPD_PIPE_ORDER` (~:323):
`segregation → policy_extraction → itemized_bills → consolidated_bills → merge_bills*
→ items_categorisation → nme_analysis → benefit_plan → audit` (*deterministic transform,
`opd.py:149`). Dependency wiring: `build_text_inputs` (~:267) renders one stage's structured
JSON into the next stage's instruction (helpers `apply_categories`, `prepare_*_input`).
Audit system prompt is assembled per doc at runtime via
`build_audit_prompt(claimed_amount, calculated_total, extracted_json)`.

Tasks: `segregation` (doc), `policy_extraction` (text, from superclaims-ai),
`itemized_bills` (doc), `consolidated_bills` (doc), `items_categorisation` (text),
`nme_analysis` (text), `benefit_plan` (text, from superclaims-ai), `audit` (doc, has a
degenerate-output repair ladder).

### 5.3 Prompts & schemas

- `tasks/prompts/opd_healthpay.py` — **2,369 lines** of verbatim-vendored prompts. Sources
  (per `docs/phase-2.5-prompt-sourcing.md`): segregation, itemized_bills,
  items_categorisation, nme, audit ← healthpay-ai; benefit_plan, policy_extraction ←
  superclaims-ai. Manually de-tuned to be model-neutral. Not synced, not configurable.
- `tasks/schemas/opd_healthpay.py` (179 lines): `DocumentSegregatorResponse`,
  `ItemizedBillsOutput`, `ConsolidatedBillsOutput`, `ItemsCategorisationOutput`,
  `NMEAnalysisResponse`, `AuditAnalysisOutput`, `BenefitPlanSelectionOutput`,
  `EkincarePolicyExtractionOutput`.
- Older `schemas/opd.py` / `prompts/bills.py` kept for Phase-1 back-compat.

### 5.4 Claim types (`tasks/claim_types/`)

`get_task_pack("OPD")` works. **`ipd.py` resolves CL/RM to `NotImplementedError` stubs** —
WS C replaces this.

## 6. Scoring & ground truth

- **Gold format** (`data/gold/*.json`, 22 files; `docs/ground-truth-format.md`):
  `{"document": <path-or-sha256>, "tasks": {<task_name>: <gold_json>}}`. Includes
  context-only feed keys `upstream_bills`, `upstream_benefits` — never scored, used to
  inject gold upstream data (`report.py` ~:36 `NON_SCORED_TASKS`).
- `scoring/field_metrics.py`: recursive deterministic diff; gold drives the field set;
  strings trimmed/lowercased exact; numbers ±1% (~:14); lists set-based precision/recall
  keyed on identifying fields (`_list_key` ~:116); per-field match counts with collapsed
  selectors (`bills[].items[].discount`); null prediction = 0;
  `accuracy = matched_leaves / total_gold_leaves`.
- `scoring/report.py`: `score_run()` upserts `Score` per result; `comparison()` per
  (task, model): mean accuracy, valid%, cost, median latency, tokens; `field_breakdown()`
  per-field match rates per model; CLI merges multiple `--run` ids.
- `scoring/scoreboard.py`: composite = `0.6*accuracy + 0.25*cost_eff + 0.15*latency_eff`
  (weights ~:19), normalized within task group; falls back to structural validity without
  gold; skipped cells excluded.
- `scoring/ground_truth_import.py`: CLI + `import_ground_truth()` upsert per
  (document, task); resolves docs by sha256/path.

## 7. `streamlit_app.py` (907 lines) — current UI, to become legacy

- `run_custom_benchmark` (~:148–345): **sequential** async loop over
  selected_docs × selected_models × pipeline-ordered tasks; each cell through
  `ModelGateway.structured`; persists; live status grid; `score_run` at end.
- Sidebar: run name; doc multiselect (from `test-docs/` — **no upload**); model multiselect
  (enabled models; gated greyed out); task multiselect; **"Gold Upstream Feed" checkbox**
  (precedent for gold-fed upstream inputs); Vertex rate-limit pause slider; GT CSV importer.
- Tabs: Leaderboard (acc-vs-cost scatter, latency bars, per-task tables, field breakdown);
  Output Inspector (side-by-side outputs for doc+task, gold, mismatches, raw prompt/response);
  Run console; Ground Truth manager; Model Catalog.

## 8. Confirmed gaps (why v2)

| # | Gap | Evidence |
|---|---|---|
| a | Bulk exists but **sequential** | no `asyncio.gather`/`create_task` anywhere (grepped) |
| b | Multi-model compare yes, **concurrent no** | same sequential loop |
| c | **No judge** | only unused `Score.judge_score` column |
| d | Prompts **hardcoded** | 2,369-line constants file; editing = code change |
| e | Dependencies first-class but **UI/config shallow**; gold-feed only global checkbox | `OPD_PIPE_ORDER`, `build_text_inputs` |
| f | **IPD stub** | `tasks/claim_types/ipd.py` raises |
| g | **No API layer / no upload / Streamlit-only UI** | grep confirmed |
| h | No Bedrock; Gemini 3.x gated; Qwen3-VL endpoint absent | catalog YAMLs |

## 9. Data & test assets

- `test-docs/` — 27 claim PDFs. `data/gold/` — 22 gold JSONs. `data/gold_exports/` — CSV
  exports + `scripts/convert_gold_exports.py`, `scripts/export_gold_*.sql`.
- `backend/tests/` — pytest suite: catalog, capability gate, docprep, persistence, scoring,
  usage normalization, OPD tasks, live Gemini (needs creds).
- `docker-compose.yml` — Postgres :5433 (+ Redis :6380 configured, unused).
- `.streamlit/config.toml`, `secrets/vertex-sa.json` (service account — do not commit
  elsewhere), `.env` (real secrets; git-ignored), `.env.example` (template).

# 00 — Colosseum v2 Master Plan

> **Audience:** implementation agents with ZERO prior context. Read this file first, then
> `01-context-colosseum.md` and `02-context-reference-pipelines.md`, then your workstream doc.
> Everything you need is in `docs/plans/` — do not rely on any prior conversation.

## 1. What Colosseum is and why this rework exists

Colosseum (`/Users/ekincare/superclaims/Colosseum`) is an LLM benchmarking platform for
insurance-claims processing agents. It runs the same prompts + mandatory structured-output
schemas across many LLM providers on real claim PDFs and compares accuracy / cost / latency.

**User's verdict on the current state:** "does the bare minimum — the name Colosseum doesn't
stand true." The concrete complaints:

1. Cannot bulk-run 20–30 PDFs for **only** a chosen agent subset (e.g. just segregation + audit).
2. Cannot run the same claims across multiple models **simultaneously** (execution is fully
   sequential) and compare properly.
3. No LLM-as-judge — user wants to evaluate results with **Gemini 3.1 Pro**.
4. UI (Streamlit, 907 lines) is not intuitive: no file upload, no proper toggles/dropdowns,
   weak comparison and results views.
5. Task pack does not faithfully mirror the production pipelines: **IPD is an unimplemented
   stub**, and per-agent input/output params (models, thinking budgets/levels,
   max_output_tokens, page-cropping) are not mirrored from the source repos.
6. When only some agents are selected, upstream dependency data must be fed correctly.
7. User's providers not usable: **AWS Bedrock** and a self-deployed **Qwen3-VL-8B**.

## 2. Confirmed product decisions (user-approved)

| Decision | Choice |
|---|---|
| UI stack | **React + FastAPI** (new `frontend/` + `backend/app/api/`). Streamlit kept untouched as legacy fallback. |
| Judge | All three modes: grade-vs-gold, grade-vs-PDF (no gold), head-to-head ranking. Default judge model `gemini-3.1-pro`, pluggable. |
| Prompts | **Synced + editable**: DB-versioned baseline seeded from the vendored prompts (provenance recorded), per-run overrides editable in UI. |
| Unselected upstream deps | Fed **from ground truth** (gold JSON). Hard error if gold missing the needed keys. |
| Reference pipelines | OPD = superclaims-ai branch `test-ekincare-v2`; IPD = healthpay-ai branch `test-fhpl`. Mirror all agents, prompts, schemas, store nodes, and runtime params. |
| New providers | AWS Bedrock (bearer token) + Qwen3-VL-8B (vLLM OpenAI-compatible). |

## 3. Repos and how to read them

| Repo | Path | Branch to read | Note |
|---|---|---|---|
| Colosseum (this repo) | `/Users/ekincare/superclaims/Colosseum` | `main` | Working tree. |
| superclaims-ai (OPD reference) | `/Users/ekincare/superclaims/superclaims-ai` | `test-ekincare-v2` | This branch IS checked out — read the working tree. |
| healthpay-ai (IPD reference) | `/Users/ekincare/superclaims/healthpay-ai` | `test-fhpl` | **NOT checked out** (tree has `test-ekincare`). Read via `git -C /Users/ekincare/superclaims/healthpay-ai show test-fhpl:<path>` and list files via `git -C … ls-tree -r test-fhpl --name-only`. Do NOT check out or modify that repo. |

Full architecture reports: `docs/plans/01-context-colosseum.md` (this repo) and
`docs/plans/02-context-reference-pipelines.md` (both reference pipelines). Raw research dumps
also exist at repo root (`arch.text`, `arch2.txt`) — the plans/ docs supersede them.

## 4. Tooling / conventions in this repo

- Python managed by **uv** (`uv sync`, `uv run …`); lint `uv run ruff check backend`; tests
  `uv run pytest backend/tests -x -q` (SQLite in tests, Postgres :5433 via `docker-compose up -d db` for live).
- ORM: SQLModel; migrations: alembic (metadata-driven — see `alembic/versions/0001_initial.py`).
- All model calls MUST go through `app.providers.gateway.ModelGateway.structured()` — never
  call LiteLLM/SDKs directly. It handles capability gating, structured output, repair
  fallback, usage normalization and cost estimation.
- Settings: `backend/app/core/config.py` (pydantic-settings). It **layers sibling repos'
  `.env` files** via `EXTERNAL_ENV_FILES` before Colosseum's own `.env` (which wins), so
  Vertex credentials are reused, not copied.
- Secrets live in `.env` (git-ignored). **Never commit secrets.**

## 5. Workstreams

| WS | Doc | Scope | Depends on |
|---|---|---|---|
| A | `03-plan-A-execution-engine.md` | Task-protocol extension (deps/DAG), prompt store, parallel run engine + RunManager, ALL alembic migrations 0003–0006 | — |
| B | `04-plan-B-providers.md` | Bedrock provider, Qwen3-VL-8B catalog entry, Gemini 3.1 Pro enablement + verify scripts | — |
| C | `05-plan-C-task-packs.md` | Full IPD task pack port (test-fhpl), OPD parity extension + reference runtime params, gold-format extension | A's Task protocol (contract §6.2 — can start immediately against the contract) |
| D | `06-plan-D-judge.md` | `scoring/judge.py`, 3 modes, judge schemas, CLI | A's migrations (JudgeComparison table is in A's 0005); gateway as-is |
| E | `07-plan-E-api.md` | FastAPI app + all routers, SSE, uploads | A (RunManager/RunSpec), contracts below |
| F | `08-plan-F-frontend.md` | React app (Vite+TS+Tailwind+shadcn/ui), all pages | E's OpenAPI (contracts below allow parallel dev with mocks) |
| — | `09-verification-and-rollout.md` | Per-WS acceptance tests, live smoke, E2E scenario, risks | all |

**Execution order:** A + B + C in parallel → D + E (after A lands) → F (after E's routes exist;
component work can start against the pinned contracts immediately). One agent per workstream.
**Only workstream A creates alembic migrations** — everyone else imports A's tables.

## 6. PINNED CONTRACTS (do not deviate; change requires updating this file)

### 6.1 RunSpec (the single run-configuration object)

Pydantic model in `backend/app/runner/spec.py` (WS A owns). JSON shape:

```jsonc
{
  "name": "seg-audit-bulk-2026-07-10",
  "pack": "OPD",                          // "OPD" | "IPD"
  "variant": null,                        // IPD only: "CL" | "RM" | "PP" (null = default)
  "selected_tasks": ["segregation", "audit"],
  "document_ids": [1, 2, 3],              // DocumentSample.id
  "model_ids": ["gemini-2.5-flash", "bedrock-claude-sonnet-4-5", "qwen3-vl-8b"],
  "upstream_mode": "gold",                // "gold" | "model" ("model" only valid when the
                                          // upstream task is also in selected_tasks)
  "prompt_overrides": {                   // optional, per task, applies to this run only
    "audit": {"system_prompt": "…", "instruction_template": "…"}
  },
  "runtime_overrides": {                  // optional, per task; falls back to reference_runtime
    "audit": {"model_id": null, "thinking_budget": 4096, "thinking_level": null,
               "max_output_tokens": 16000, "timeout_s": 300}
  },
  "concurrency": {"global": 16,
                   "per_provider": {"vertex_ai": 4, "openai_compatible": 8,
                                     "bedrock": 4, "xai": 2}},
  "judge": {"enabled": true, "model_id": "gemini-3.1-pro",
             "modes": ["gold_grade", "head_to_head"]},  // subset of the 3 modes
  "confirm_large": false                  // must be true when the cell matrix exceeds 100
}
```

Stored verbatim in `BenchmarkRun.spec` (JSONB, migration 0004).

### 6.2 Task protocol extension (`backend/app/tasks/base.py`)

The existing frozen dataclass `Task` (name, system_prompt, instruction, schema,
requires_documents, default_page_ranges, document_types, is_text_task, build_input,
render_instruction) is **extended, not replaced** — existing fields keep their semantics.
New fields (all with defaults so existing OPD_TASKS keep working during the transition):

```python
@dataclass(frozen=True)
class ReferenceRuntime:
    model_id: str | None = None          # catalog id the source repo used (informational default)
    thinking_budget: int | None = None   # tokens; None = provider default
    thinking_level: str | None = None    # "minimal" | "low" | "medium" (gemini-3.x style)
    max_output_tokens: int | None = None
    timeout_s: float | None = None

@dataclass(frozen=True)
class Task:
    ...existing fields...
    depends_on: tuple[str, ...] = ()          # names of upstream tasks in the same pack
    deterministic: bool = False               # non-LLM transform (merge_bills, patient_summary, validation)
    reference_runtime: ReferenceRuntime = ReferenceRuntime()
    gold_feed_keys: tuple[str, ...] = ()      # gold["tasks"] keys that satisfy this task's
                                              # upstream inputs when deps are NOT selected
                                              # (e.g. audit: ("nme_analysis", "segregation", ...))
    # Deterministic tasks implement:  run_transform(upstream: dict[str, Any]) -> dict
    # LLM tasks build instruction via existing render_instruction(**context); the engine
    # resolves `context` from upstream outputs or gold (see 03 doc, "input resolution").
```

A **task pack** is exposed as `TaskPack` (WS A defines in `tasks/base.py`):
`TaskPack(name, tasks: dict[str, Task], order: list[str])` with helpers
`dependency_graph()` and `resolve_subset(selected, upstream_mode)` returning the execution
DAG + the list of gold keys required per document.

### 6.3 Progress events (engine → SSE → frontend)

```jsonc
// per cell:
{"type": "cell", "run_id": 12, "document_id": 3, "document": "REQ65CYP9E0",
 "model_id": "gemini-2.5-flash", "task": "audit",
 "status": "running" | "succeeded" | "failed" | "skipped",
 "latency_ms": 4321, "cost_usd": 0.0123, "error": null, "skip_reason": null}
// run-level:
{"type": "run", "run_id": 12, "status": "running" | "completed" | "failed" | "cancelled",
 "counts": {"total": 62, "succeeded": 58, "failed": 1, "skipped": 3, "pending": 0}}
```

### 6.4 API surface (WS E implements; WS F consumes)

Base path `/api`. FastAPI app: `backend/app/api/main.py`, run with
`uv run uvicorn app.api.main:app --reload --port 8100` (from `backend/`).

| Method & path | Purpose | Body / returns (sketch) |
|---|---|---|
| `POST /api/runs` | create + launch | body = RunSpec → `{run_id, status}` |
| `POST /api/runs/dry-run` | validate without launching | body = RunSpec → `{layers, gold_requirements, cost_estimate}` or 422 `{missing_gold}` |
| `GET /api/runs` | list runs | `[{run_id, name, status, created_at, counts, spec}]` |
| `GET /api/runs/{id}` | status + cell grid | `{run, cells: [{document, model, task, status, latency_ms, cost_usd, error}]}` |
| `GET /api/runs/{id}/events` | SSE stream of §6.3 events | `text/event-stream` |
| `POST /api/runs/{id}/cancel` | cancel | `{status}` |
| `GET /api/runs/{id}/results` | full results | per-cell parsed_output, prompts, usage, scores |
| `POST /api/runs/{id}/judge` | trigger judge | body `{model_id, modes}` → job status |
| `GET /api/runs/{id}/leaderboard` | scoreboard | per (task, model): accuracy, valid%, cost, latency, composite, judge aggregates |
| `GET /api/runs/{id}/field-breakdown` | per-field match rates | `{task, fields: [{path, per_model: {model: rate}}]}` |
| `GET /api/runs/{id}/side-by-side?document_id=&task=` | outputs of all models + gold + judge | |
| `POST /api/documents` | multipart PDF upload (multi-file) | → `[{id, filename, sha256, page_count}]` |
| `GET /api/documents` / `DELETE /api/documents/{id}` | list/remove | |
| `GET /api/gold/{document_id}` / `PUT` | read/write gold JSON | |
| `POST /api/gold/import` | CSV/JSON import | |
| `GET /api/packs` | task packs, dependency graph, reference runtimes, gold_feed_keys | drives Run Builder |
| `GET /api/prompts?pack=` | active prompts per task | |
| `GET/POST /api/prompts/{pack}/{task}/versions` | version history / new version | |
| `GET /api/catalog` | models + capabilities + pricing + gate reasons | |
| `POST /api/catalog/{model_id}/verify` | live smoke-test a model | `{ok, error?}` |

### 6.5 DB additions (ALL owned by WS A — migrations `0003`–`0006`)

- `0003_prompt_versions`: table `promptversion(id, pack, task_name, version int,
  system_prompt text, instruction_template text, source_repo, source_branch, source_path,
  active bool, created_at)`; unique `(pack, task_name, version)`; at most one active per
  `(pack, task_name)`.
- `0004_run_spec`: `benchmarkrun.spec` JSONB (nullable for old rows) + `benchmarkrun.pack` str.
- `0005_judge`: table `judgecomparison(id, run_id FK, task_name, document_id FK, mode,
  judge_model, payload JSONB, rationale text, cost_usd, created_at)`. Per-result grades go in
  the existing `score.judge_score` JSONB (already in schema, currently unused).
- `0006_document_origin`: `documentsample.origin` str default `"test-docs"` (`"upload"` for
  uploaded files, stored under `data/uploads/`).

### 6.6 Environment variables (add to `.env.example`; real values in `.env` only)

```bash
# AWS Bedrock — bearer token API key. NOTE: the token is presigned and EXPIRES (~12h).
# Refresh: obtain a new key from the AWS console/issuer and replace this value; a stale
# token surfaces as 403 ExpiredTokenException from scripts/verify_bedrock.py.
AWS_BEARER_TOKEN_BEDROCK=
AWS_REGION_NAME=ap-south-1

# Self-deployed Qwen3-VL-8B (vLLM, OpenAI-compatible)
QWEN_VL_BASE_URL=http://15.252.27.168:8000/v1
QWEN_VL_API_KEY=EMPTY   # vLLM default; keep "EMPTY" unless the server sets a key
```

The user HAS a working Bedrock bearer token and the Qwen endpoint is live
(`curl $QWEN_VL_BASE_URL/chat/completions` with model `Qwen/Qwen3-VL-8B-Instruct` answers).
Gemini 3.1 Pro (`gemini-3.1-pro-preview`) is available on the **superclaims-ai Vertex
project**, whose `.env` is already layered via `EXTERNAL_ENV_FILES` — see WS B doc.

### 6.7 Model id naming (catalog)

Catalog ids are Colosseum-internal (e.g. `gemini-2.5-flash`). New entries:
`qwen3-vl-8b` (openai_compatible) and `bedrock-*` ids (e.g. `bedrock-claude-sonnet-4-5`,
`bedrock-nova-pro`) — WS B fixes the exact list after running the verify script.
`gemini-3.1-pro` is the judge default id (maps to `gemini-3.1-pro-preview` on Vertex).

## 7. End-state acceptance (the product must do all of this)

1. Upload 25 claim PDFs via the UI (drag-drop, bulk).
2. Pick pack=OPD, agents = segregation + audit only; UI shows audit's upstream deps will be
   fed **from gold** and validates gold exists for all 25 docs (clear per-doc errors if not).
3. Pick 3+ models across providers (Vertex Gemini, Bedrock, Qwen3-VL-8B), optionally edit the
   audit prompt for this run.
4. Launch: cells execute **in parallel** (per-provider concurrency caps respected), live
   progress grid updates via SSE, run is cancellable.
5. Results: leaderboard, per-field breakdown, side-by-side outputs vs gold with mismatch
   highlighting, raw prompt/response inspector, token/cost/latency everywhere.
6. Trigger judge (gemini-3.1-pro) in any of the 3 modes; verdicts and rankings render in UI.
7. Same flow works for pack=IPD with the full ported healthpay pipeline, mirroring source
   runtime params (visible in UI as per-agent defaults).

## 8. Risks / cautions (all agents read this)

- **Bedrock token expiry (~12h)**: treat 403s as expired-token first; never bake the token
  into code, tests, or fixtures.
- **Gemini 3.x access**: Colosseum's previously-used Vertex project 404s on Gemini 3.x; the
  superclaims-ai project works. WS B must verify before WS D relies on it; judge falls back
  to `gemini-2.5-pro` if 3.1 unavailable (config flag).
- **Structured-output fidelity**: healthpay-ai prompts embed JSON-schema-as-text and repair
  with `json_repair` + continuation loops; Colosseum uses Instructor structured output.
  Prompts are ported verbatim; the difference is documented per task in WS C. Do not "fix"
  prompts to remove the textual schema — it is part of the benchmarked prompt.
- **Cost control**: any live verification uses `gemini-2.5-flash-lite` (or the cheapest
  enabled model) on ≤2 PDFs unless the doc says otherwise.
- **vLLM endpoint reachability**: `15.252.27.168:8000` may be network-restricted; verify with
  the health call before catalog-enabling.
- Do not modify `streamlit_app.py` behavior; do not touch the two reference repos.

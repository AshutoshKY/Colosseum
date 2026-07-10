# 07 — Workstream E: FastAPI Layer

> Prerequisites: `00-master-plan.md` (§6.4 API contract — implement it EXACTLY; frontend
> is built against it), `01-context-colosseum.md`. Depends on WS A (`RunSpec`,
> `RunManager`, prompt store, migrations); judge route imports WS D's `judge_run` (guard
> with a 501 response if not yet merged).

## Goal

`backend/app/api/` — the complete HTTP surface for the React frontend: run lifecycle with
SSE progress, document upload, gold management, prompt versioning, catalog, packs metadata,
and comparison/results endpoints. FastAPI + uvicorn; serves the built frontend statically.

## Files

| File | Action |
|---|---|
| `backend/app/api/main.py` | NEW — app factory: CORS (localhost dev), routers, `/api/health`, static mount of `frontend/dist` at `/` (if exists), OpenAPI title/version |
| `backend/app/api/deps.py` | NEW — `get_session` (wrap `db.engine.session_scope`), `get_run_manager` |
| `backend/app/api/schemas.py` | NEW — response models (RunOut, CellOut, DocumentOut, PackOut, LeaderboardRow, …) |
| `backend/app/api/routers/runs.py` | NEW |
| `backend/app/api/routers/documents.py` | NEW |
| `backend/app/api/routers/gold.py` | NEW |
| `backend/app/api/routers/prompts.py` | NEW |
| `backend/app/api/routers/catalog.py` | NEW |
| `backend/app/api/routers/packs.py` | NEW |
| `backend/app/api/routers/comparison.py` | NEW |
| `pyproject.toml` | add fastapi, uvicorn, sse-starlette (or hand-rolled SSE), python-multipart |
| `backend/tests/test_api_*.py` | NEW — httpx `AsyncClient` tests per router |
| `README.md` | run instructions (`uv run uvicorn app.api.main:app --port 8100`) |

## Endpoint specs (contract 00 §6.4 — details)

### runs.py
- `POST /api/runs` — body: RunSpec JSON (validated by WS A's pydantic model; also runs
  `spec.validate_gold` and returns 422 with a machine-readable
  `{missing_gold: {document_id: [keys]}}` when upstream_mode=gold and gold is incomplete).
  On success: `RunManager.launch(spec)` → `202 {run_id, status:"running"}`.
- `POST /api/runs/dry-run` — same validation WITHOUT launching; returns the resolved plan:
  `{layers, gold_requirements, cost_estimate}` (cost estimate: docs × models × tasks with
  per-model pricing heuristics from the rate card — rough is fine, label it estimate).
  The Run Builder calls this on every change.
- `GET /api/runs` — paged list, newest first: `{run_id, name, pack, status, created_at,
  counts, spec}`.
- `GET /api/runs/{id}` — run + full cell grid (from RunCell/RunResult):
  `{run, cells:[{document_id, document_name, model_id, task, status, latency_ms, cost_usd,
  error, skip_reason}]}`.
- `GET /api/runs/{id}/events` — **SSE** (`text/event-stream`): subscribe to
  `RunManager.subscribe(run_id, replay=True)`; heartbeat comment every 15s; stream closes
  on terminal run status. If the run is not live in this process (restart), emit one
  synthetic `run` event from DB state and close — the client falls back to polling
  `GET /runs/{id}`.
- `POST /api/runs/{id}/cancel` → `{status}`.
- `GET /api/runs/{id}/results` — per-cell detail incl. `parsed_output`, `prompt_system`,
  `prompt_instruction`, `raw_response` (behind `?include_raw=true`), usage/costs, score
  (field_metrics + judge_score).
- `POST /api/runs/{id}/judge` — body `{model_id?, modes:[…]}` → runs `judge_run` as an
  asyncio background task; progress observable via `GET /runs/{id}` judge fields; 501 if
  judge module absent.

### documents.py
- `POST /api/documents` — multipart, MULTIPLE files; each: save to `data/uploads/`
  (sanitized filename, collision-suffixed), sha256-dedupe via existing
  `runner/persistence.py::register_document` (origin="upload"), page count via
  `utils/pdf.py` → `[{id, filename, sha256, page_count, has_gold}]`. Reject non-PDF
  (magic-bytes check) with 415. Max 50 files / 300 MB per request.
- `GET /api/documents` — all docs (test-docs + uploads) with `has_gold` per pack task keys
  summary. `DELETE /api/documents/{id}` — uploads only (403 for test-docs assets).

### gold.py
- `GET /api/gold/{document_id}` → `{document_id, tasks: {…}}` (404 → empty tasks).
- `PUT /api/gold/{document_id}` — body `{tasks: {task_name: json}}` upsert via
  `scoring/ground_truth_import.import_ground_truth`.
- `POST /api/gold/import` — file upload (JSON in `data/gold` format, or the CSV export
  format handled by `scripts/convert_gold_exports.py` logic) → import report.

### prompts.py
- `GET /api/prompts?pack=OPD` → per task: active version, source provenance, whether a
  code-constant fallback differs from the active DB version.
- `GET /api/prompts/{pack}/{task}/versions` → full history.
- `POST /api/prompts/{pack}/{task}/versions` — body `{system_prompt,
  instruction_template, activate: bool}` → new version (version = max+1).
- `POST /api/prompts/preview` — body `{pack, task, system_prompt?,
  instruction_template?, sample_document_id?}` → rendered prompt with sample context
  (uses gold of the sample doc for upstream slots) so the UI can preview `{{VARS}}` filling.

### catalog.py
- `GET /api/catalog` → from `providers/registry.py::catalog_summary()` + pricing +
  `gate_reason()` per model, grouped by provider/family.
- `POST /api/catalog/{model_id}/verify` — calls WS B's `scripts/verify_model.py` logic
  (import the function, don't shell out) → `{ok, error?, latency_ms}`; on success flip the
  in-memory registry `verified` (YAML persistence is manual — return
  `yaml_snippet` for the operator).

### packs.py
- `GET /api/packs` → for each pack (+variants): ordered tasks with `{name, deterministic,
  depends_on, document_types, is_text_task, reference_runtime, gold_feed_keys}` — this
  single endpoint powers the Run Builder's dependency visualization and gold-feed chips.

### comparison.py
- `GET /api/runs/{id}/leaderboard` — `scoring/report.py::comparison()` + scoreboard
  composite + WS D `judge_aggregates` merged: rows per (task, model).
- `GET /api/runs/{id}/field-breakdown?task=` — `field_breakdown()` reshaped
  `{fields:[{path, per_model:{model: rate}}]}`.
- `GET /api/runs/{id}/side-by-side?document_id=&task=` — all models' parsed_output +
  gold + field_metrics mismatches + judge verdicts/ranking for that (doc, task).

## Implementation notes

- Sync SQLModel sessions inside async routes: wrap DB-heavy work in
  `fastapi.concurrency.run_in_threadpool` (the engine already handles its own persistence
  in worker threads — check WS A's implementation and follow the same pattern).
- SSE: keep it dependency-light (`sse-starlette` or a small generator with
  `media_type="text/event-stream"`); ensure client disconnects cancel the subscription.
- No auth (internal tool) but bind docs: mention `--host 127.0.0.1` default.
- OpenAPI must be complete/accurate — WS F generates a typed client from
  `http://localhost:8100/openapi.json`.

## Acceptance criteria

1. Full pytest coverage per router with httpx AsyncClient + SQLite + a fake RunManager
   (launch/subscribe/cancel): create→events→results→judge flow, dry-run gold validation
   errors, multipart multi-file upload with dedupe, prompt version precedence surfaced,
   packs payload contains dependency metadata for BOTH packs.
2. `uv run uvicorn app.api.main:app` boots with docker Postgres; `/api/health` ok;
   `/openapi.json` validates (run `openapi-spec-validator` in a test).
3. SSE integration test: launch a fake 4-cell run, assert event ordering
   (cell running→succeeded ×4 → run completed) and late-subscriber replay.
4. Manual live check: create a tiny real run via curl (2 docs × flash-lite ×
   segregation), watch `curl -N …/events`, verify leaderboard JSON.
5. ruff + full suite green.

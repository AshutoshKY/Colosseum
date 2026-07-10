# 03 — Workstream A: Task DAG · Prompt Store · Parallel Execution Engine · DB Migrations

> Prerequisites: read `00-master-plan.md` (contracts §6), `01-context-colosseum.md`.
> You own ALL alembic migrations (0003–0006) including the judge table (used by WS D) and
> the document-origin column (used by WS E). Other workstreams import your tables.

## Goal

Replace the sequential runner with a dependency-aware, truly parallel execution engine
driven by a single `RunSpec`, with a DB-versioned prompt store and gold-fed upstream
injection for agent subsets. Provide the `RunManager` API that the FastAPI layer (WS E)
calls to launch/observe/cancel runs.

## Deliverables (files)

| File | Action |
|---|---|
| `backend/app/tasks/base.py` | extend `Task` + add `ReferenceRuntime`, `TaskPack` (contract 00 §6.2) |
| `backend/app/runner/spec.py` | NEW — `RunSpec` pydantic model (contract 00 §6.1) + validation |
| `backend/app/runner/engine.py` | NEW — DAG builder + parallel executor |
| `backend/app/runner/run_manager.py` | NEW — in-process run registry, events, cancel |
| `backend/app/runner/upstream.py` | NEW — upstream input resolution (model output vs gold) |
| `backend/app/models/prompt.py` | NEW — `PromptVersion` SQLModel |
| `backend/app/models/judge.py` | NEW — `JudgeComparison` SQLModel (WS D consumes) |
| `backend/app/models/benchmark.py` | add `spec` JSONB + `pack` to `BenchmarkRun` |
| `backend/app/models/document.py` | add `origin` field |
| `backend/app/prompts/store.py` | NEW — prompt resolution (override → DB active → code constant) |
| `scripts/seed_prompts.py` | NEW — seed PromptVersion v1 from vendored constants |
| `alembic/versions/0003_prompt_versions.py` … `0006_document_origin.py` | NEW (contract 00 §6.5) |
| `backend/tests/test_engine.py`, `test_prompt_store.py`, `test_upstream.py`, `test_run_spec.py` | NEW |

Do NOT modify: `providers/gateway.py` (WS B), `tasks/opd.py` task definitions beyond adding
the new protocol fields' values (coordinate with WS C — you add the fields with safe
defaults; WS C fills real `depends_on`/`reference_runtime`/`gold_feed_keys`). To be
unblocked, hardcode an interim `OPD_DEPENDS = {...}` map in `engine.py` mirroring
`OPD_PIPE_ORDER` semantics, delete it once WS C lands (leave a `TODO(WS-C)`).

## Design

### 1. Task protocol & TaskPack (`tasks/base.py`)

Implement contract 00 §6.2 exactly. Add:

```python
class TaskPack:
    name: str                      # "OPD" | "IPD"
    tasks: dict[str, Task]
    order: list[str]               # topological reference order

    def dependency_graph(self) -> dict[str, tuple[str, ...]]: ...
    def resolve_subset(self, selected: list[str], upstream_mode: str) -> SubsetPlan:
        """Validate selection, return execution layers + per-task input sources.
        SubsetPlan.layers: list[list[str]]  (topological layers among SELECTED tasks,
                                             deterministic transforms included)
        SubsetPlan.gold_requirements: dict[task, tuple[gold_keys_needed]]
          — for every selected task whose depends_on includes an UNSELECTED task,
            the gold keys that must exist for each document (from Task.gold_feed_keys).
        Raises SubsetError listing missing/unknown task names or cycles.
        """
```

Rules:
- `upstream_mode="model"`: every `depends_on` of a selected task must also be selected
  (else validation error naming the missing tasks).
- `upstream_mode="gold"`: unselected upstream tasks are NOT executed; their outputs are
  read from gold (see §3). Selected upstream tasks still feed their live outputs downstream
  (gold is only for the gaps). Deterministic tasks (merge_bills, patient_summary,
  validation) are auto-included (they're free) whenever selected tasks need them AND their
  own inputs are available (live or gold); otherwise their output too comes from gold.

### 2. RunSpec (`runner/spec.py`)

Pydantic model matching contract 00 §6.1, with validators: pack exists
(`tasks.claim_types.get_task_pack`), tasks exist in pack, models exist + enabled in
registry (`providers.registry`), documents exist in DB, judge model exists,
concurrency values ≥1. `spec.validate_gold(session)` → per-document report of missing
gold keys (used by both engine pre-flight and the API's dry-run check).

### 3. Upstream input resolution (`runner/upstream.py`)

```python
class UpstreamResolver:
    def __init__(self, session, document: DocumentSample, gold: dict | None,
                 live_outputs: dict[str, Any]): ...
    def get(self, task_name: str) -> Any:
        """live_outputs[task_name] if the task ran in this chain, else
        gold["tasks"][task_name] (also accepts legacy aliases: upstream_bills → merge_bills,
        upstream_benefits → benefits). Raises MissingUpstreamData(task, doc) otherwise."""
```

- Gold source: `GroundTruth` rows for the document (all tasks), loaded once per doc.
- The context rendered into a text task's instruction is built exactly like today's
  `tasks/opd.py::build_text_inputs` — reuse those helpers; do not re-implement the
  JSON-rendering logic. For IPD, WS C supplies equivalent builders; the engine only calls
  `task.render_instruction(**context)` / `task.run_transform(upstream)` /
  `task.build_input(...)`.
- Cells whose upstream resolution fails are persisted as `failed` with
  `error="missing_upstream:<task>:<detail>"` — not skipped (skipped is reserved for
  capability gating), and downstream cells in that chain fail fast with the same reason.

### 4. Engine (`runner/engine.py`)

```python
async def execute_run(run_id: int, spec: RunSpec, events: EventSink) -> None
```

- Pre-flight: create `RunCell` rows for the full matrix docs × models × selected tasks
  (status `pending`) — the DB grid is the source of truth the UI can re-poll.
- Concurrency primitives (module-level per run): `asyncio.Semaphore` per provider (from
  `spec.concurrency.per_provider`, defaults in contract) + one global semaphore. Provider
  of a model comes from `get_capability(model_id).provider`.
- Scheduling: for each (document × model) build a **chain coroutine**:
  - iterate `SubsetPlan.layers`; within a layer run all tasks with
    `asyncio.gather(*cells)` (e.g. itemized ∥ consolidated ∥ claim_form ∥ cheque_bank);
    layers run in order so `depends_on` outputs exist.
  - each LLM cell: acquire global+provider semaphores → resolve prompt (see §5) → resolve
    inputs (upstream resolver; doc tasks call `task.build_input(document.path,
    page_ranges=…)` — page ranges computed from the segmentation output exactly like
    `streamlit_app.run_custom_benchmark` does today) → `ModelGateway.structured(...)`
    with per-task runtime (spec.runtime_overrides > task.reference_runtime) →
    `persist_cell_result(...)` → `events.emit(cell …)`.
  - deterministic cells run inline (no semaphore), persisted with `structured_method="deterministic"`,
    zero cost, and their output recorded in `RunResult.parsed_output` so scoring/inspection work.
- All chains launched with `asyncio.gather(*chains, return_exceptions=True)`; one chain's
  failure never kills the run. On completion: `score_run(run_id)` (existing
  `scoring/report.py`), set run status, emit final run event. If `spec.judge.enabled`,
  call WS D's `judge_run(run_id, spec.judge)` (import guarded so WS A merges before WS D:
  `try: from app.scoring.judge import judge_run except ImportError: log+skip`).
- Cancellation: cooperative — RunManager cancels the top-level task; engine catches
  `asyncio.CancelledError`, marks pending cells `skipped` (skip_reason "cancelled"), sets
  run status `cancelled`, re-raises nothing.
- Retries/rate limits: rely on gateway retries; on 429-class errors apply per-provider
  exponential backoff (jittered, max 3) at the cell level before failing.

### 5. Prompt store (`models/prompt.py`, `prompts/store.py`, `scripts/seed_prompts.py`)

- `PromptVersion` per contract 00 §6.5.
- `store.py::resolve_prompt(pack, task, overrides) -> ResolvedPrompt(system_prompt,
  instruction_template, source)` with precedence: run override → active DB version → code
  constant (from the task object). `source` recorded so RunResult provenance is honest
  (RunResult already stores the literal prompts used — keep that).
- `seed_prompts.py`: iterate both packs' tasks, insert version 1 rows (active=True) with
  provenance: source_repo (`healthpay-ai`/`superclaims-ai`/`colosseum`), source_branch
  (`test-fhpl`/`test-ekincare-v2`), source_path (original prompt file). Idempotent
  (skip if (pack, task, 1) exists). Templated prompts (audit) are stored with their
  `{{VARS}}` intact; rendering stays in the task's builder.

### 6. RunManager (`runner/run_manager.py`)

```python
class RunManager:  # process-wide singleton (module-level instance)
    async def launch(self, spec: RunSpec) -> int          # creates BenchmarkRun(+spec), spawns execute_run task
    def status(self, run_id) -> RunStatus                  # DB-backed + live counts
    async def cancel(self, run_id) -> bool
    def subscribe(self, run_id) -> AsyncIterator[dict]     # per-subscriber asyncio.Queue of §6.3 events
```

- Events: contract 00 §6.3. Keep last N=1000 events per run in a ring buffer so an SSE
  client connecting late gets a snapshot (`replay=True` param).
- Single-process assumption (uvicorn single worker) is acceptable and must be documented in
  the module docstring; DB cell status lets a UI recover even if the process restarts.

### 7. Migrations

0003–0006 per contract 00 §6.5. Import new models in `alembic/env.py` (follow the existing
pattern used for 0001/0002). Test upgrade+downgrade against a scratch SQLite AND the
docker Postgres.

## Acceptance criteria

1. `TaskPack.resolve_subset(["segregation","audit"], "gold")` on OPD returns 2 layers and
   gold requirements for audit's unselected deps; selecting `["audit"]` with
   `upstream_mode="model"` raises listing the missing upstream tasks.
2. A run of 3 docs × 2 models × (segregation+audit, gold upstream) creates 12 cells,
   executes with observable concurrency (wall-time << serial sum; assert ≥2 cells
   overlapping via timestamps in test with a fake gateway), persists results, scores.
3. Per-provider semaphore respected (fake gateway asserts max in-flight per provider).
4. Cancel mid-run: pending cells → skipped/cancelled, run status `cancelled`, no orphan
   asyncio tasks (assert via `asyncio.all_tasks()`).
5. Missing gold → cell failed with `missing_upstream:` error; downstream chain fails fast;
   other chains unaffected.
6. Prompt resolution precedence proven by test (override beats DB beats constant); seeding
   idempotent; RunResult rows contain the exact prompts used.
7. `uv run pytest backend/tests -x -q` green; `uv run ruff check backend` clean;
   migrations up/down clean on SQLite + Postgres.

## Verification (live)

With docker Postgres up and Vertex creds present:
`uv run python -m app.runner.engine --smoke` (add a `__main__` that builds a tiny RunSpec:
2 docs from `test-docs/`, model `gemini-2.5-flash-lite`, tasks segregation+itemized_bills,
upstream_mode model) — confirm parallel execution in logs, rows in DB, scoreboard prints.

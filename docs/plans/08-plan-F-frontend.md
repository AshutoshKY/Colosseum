# 08 — Workstream F: React Frontend

> Prerequisites: `00-master-plan.md` (§6.3 events, §6.4 API — your data source of truth),
> `07-plan-E-api.md`. Build against `http://localhost:8100/openapi.json` (generate a typed
> client); until WS E is live, develop against MSW mocks that mirror the contract exactly.

## Goal

A genuinely intuitive benchmarking UI replacing Streamlit as the primary interface. The
user's explicit asks: provider selector, model selector, prompt viewer/editor, agent
selector with correct dependency handling, single + bulk file upload, pre-run checks,
live progress, comparison and results that are "intuitive and correct".

## Stack & scaffold

- `frontend/` — Vite + React 18 + TypeScript + Tailwind + **shadcn/ui** components +
  TanStack Query (server state) + TanStack Table (grids) + Recharts (charts) +
  `openapi-typescript`/`openapi-fetch` for the API client. React Router with 6 routes.
- Dev: `npm run dev` (proxy `/api` → `localhost:8100` in `vite.config.ts`). Build:
  `npm run build` → `frontend/dist` (served statically by the API app).
- Dark/light theme via Tailwind `dark:` + a toggle; system default.
- State rules: ALL server data through TanStack Query hooks in `src/api/hooks.ts`; run
  builder form state in a single `RunBuilderContext` (mirrors RunSpec shape 1:1 so submit
  is a passthrough).

## Pages (React Router)

### 1. `/` → Run Builder (the centerpiece)
Layout: 3-step vertical flow with a sticky right-hand **Run Summary** panel (live cost
estimate + validation status from `POST /api/runs/dry-run`, launch button).

- **Step 1 — Documents**: table of `GET /api/documents` (name, pages, origin, has_gold
  badges) with checkbox multi-select + search; **drag-drop upload zone** (multi-file PDF →
  `POST /api/documents`, progress bars, dedupe notices "already exists as #12").
- **Step 2 — Pipeline**: pack toggle (OPD | IPD [+variant dropdown for IPD: default/PP]);
  **agent selector rendered as a dependency graph** (from `GET /api/packs`): each task a
  node chip (LLM vs deterministic styled differently), edges = depends_on; clicking toggles
  selection; unselected upstream deps of selected tasks auto-annotate with an amber
  **"fed from gold"** chip; upstream_mode toggle (gold | model — "model" auto-selects
  upstream nodes and explains why). Below the graph: per-selected-task expandable row with
  (a) **prompt viewer/editor** — fetched from `GET /api/prompts`, monaco-style diff view
  baseline-vs-override, "reset to baseline", per-run override only (banner links to
  Prompts page for permanent versions); (b) runtime params (model override dropdown,
  thinking budget/level, max_output_tokens, timeout) prefilled from `reference_runtime`
  with "source default" hints.
- **Step 3 — Models**: grouped by provider (Vertex/Gemini, Bedrock, OpenAI-compatible,
  xAI) with capability badges (PDF, vision, text-only, thinking), pricing per 1M tokens,
  disabled models greyed with `gate_reason` tooltip; multi-select; "verify" button per
  model (`POST /api/catalog/{id}/verify`). Concurrency accordion (global + per-provider
  spinners, defaults from contract). **Judge accordion**: enable toggle, judge model
  dropdown, mode checkboxes (grade vs gold / grade vs document / head-to-head) with
  one-line explanations.
- Validation UX: dry-run errors render inline — e.g. "3 documents missing gold for
  `nme_analysis` needed by audit" with per-document expandable list and a deep-link to the
  gold editor. Launch disabled until dry-run passes.

### 2. `/runs` → Runs list
Table: name, pack, status pill, created, progress bar (counts), cost so far, actions
(open, cancel). Auto-refresh via query polling every 5s while any run is `running`.

### 3. `/runs/:id` → Live Run
- **Progress grid**: rows = documents, column groups = models, sub-columns = tasks; cell =
  status dot (pending/running/succeeded/failed/skipped) with tooltip (latency, cost,
  error). Data: initial `GET /api/runs/{id}` then **SSE** `GET /api/runs/{id}/events`
  (EventSource; on error/close fall back to 3s polling — the API emits a synthetic event
  when the run isn't live in-process).
- Header: run status, counts, elapsed, running cost total, cancel button (confirm dialog).
- Failure drawer: click a failed cell → error, retries, raw prompt, raw response.
- On terminal status: banner link "View results →".

### 4. `/runs/:id/results` → Results
Tabs:
- **Leaderboard**: per-task tables (rows = models: accuracy, valid%, judge score, mean
  rank/win-rate, cost/doc, median latency, composite) + two charts (accuracy-vs-cost
  scatter with model labels; latency box/bar). Follow the `dataviz` skill conventions if
  charts are added later; keep colors consistent per model across all charts.
- **Side-by-side**: doc + task pickers → columns per model: parsed_output rendered as a
  collapsible JSON tree with **field-level mismatch highlighting vs gold** (red =
  mismatch, green = match, grey = not in gold; from field_metrics + judge field_verdicts
  tooltips with explanations); gold column pinned first; raw prompt/response drawer per
  cell.
- **Field breakdown**: per-task heatmap-style table — rows = field paths, columns =
  models, cell = match rate (color-scaled), sortable to find systematically weak fields.
- **Judge**: verdict cards (modes 1/2: overall score + summary + worst fields) and
  head-to-head ranking table (per doc + aggregate win matrix). "Run judge" panel if the
  run wasn't judged: model + modes → `POST /api/runs/{id}/judge`.

### 5. `/datasets` → Documents & gold
Documents table (upload/delete) + **gold editor**: pick doc → per-task JSON editors
(validated against the pack's task keys; `PUT /api/gold/{document_id}`), import button
(`POST /api/gold/import`), per-doc "gold coverage" chips (which feedable keys exist).

### 6. `/prompts` and `/catalog`
- Prompts: pack tabs → tasks list → version history timeline (provenance: source repo /
  branch / path), view any version, create new version (activate toggle), diff any two.
- Catalog: model cards grouped by provider — capabilities, pricing, enabled/verified,
  gate reason, verify button.

## Component tree (key custom components)

```
src/
  api/ (generated client + hooks.ts + sse.ts)
  components/
    DependencyGraph.tsx      // pack DAG w/ selectable nodes + gold-feed chips (SVG or reactflow)
    PromptEditor.tsx         // baseline/override diff editor
    ModelPicker.tsx          // provider-grouped multiselect w/ badges
    UploadZone.tsx           // drag-drop multi-PDF w/ progress
    RunGrid.tsx              // live docs×models×tasks grid (virtualized for 30×5×13)
    JsonDiffTree.tsx         // collapsible JSON w/ per-field verdict coloring
    LeaderboardTable.tsx / FieldBreakdown.tsx / JudgePanel.tsx / CostEstimate.tsx
  pages/ (RunBuilder, Runs, RunLive, RunResults, Datasets, Prompts, Catalog)
```

## Acceptance criteria

1. `npm run build` clean; `npm run lint` (eslint+ts strict) clean; vitest unit tests for
   DependencyGraph selection logic (gold-chip derivation from packs payload), RunSpec
   assembly (context → POST body matches contract §6.1 byte-for-byte for a fixture), SSE
   hook fallback-to-polling, JsonDiffTree verdict coloring.
2. E2E happy path with Playwright against MSW mocks: upload 3 PDFs → select
   segregation+audit (gold chips appear for audit deps) → pick 3 models → edit audit
   prompt → dry-run shows missing-gold error → fix via mocked gold → launch → live grid
   transitions → results tabs render (leaderboard, side-by-side with mismatch colors,
   judge rankings).
3. The full flow works against the REAL API (WS E) locally with 2 docs ×
   gemini-2.5-flash-lite × segregation — document this in `frontend/README.md`.
4. Empty/edge states designed: no documents, no gold, no judge, cancelled run, failed
   cells, SSE-unavailable (post-restart) run.
5. Responsive down to 1280px; dark + light themes both legible.

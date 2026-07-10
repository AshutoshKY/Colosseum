# Colosseum

A **model-agnostic LLM benchmark platform** for health-claims document processing.
Runs the *same* prompts, *same* sample documents, and *same* mandatory structured-output
schemas across *many* models/providers, capturing accuracy, confidence, performance, and
cost so we can pick the most cost-efficient model per task.

See [`docs/plan.md`](docs/plan.md), [`docs/project-overview.md`](docs/project-overview.md),
and [`docs/models-and-caveats.md`](docs/models-and-caveats.md).

## Status: Colosseum v2

Implemented:

- Dependency-aware parallel OPD/IPD runs with gold-fed subset execution, per-provider
  concurrency limits, cancellation, SSE progress, prompt versions, and bulk PDF upload.
- Vertex, Bedrock, and OpenAI-compatible provider plumbing with verified catalog gating.
- Gemini judge modes for gold grading, document grading, and anonymized head-to-head ranking.
- FastAPI API plus the React run builder, live grid, dataset/gold editor, results, prompts,
  catalog, field breakdown, and judge views.

- Project scaffold (`pyproject.toml`, `docker-compose.yml` for Postgres + Redis, `.env.example`).
- `core/` config (pydantic-settings, layers in external `.env` files) + logging.
- `models/` SQLModel tables + `db/` engine/session + Alembic migration.
- `providers/` core: capability profiles, registry (matched to `docs/models-and-caveats.md`),
  Gemini-Vertex adapter, `ModelGateway.structured()` via **Instructor over LiteLLM** with a
  free-text → JSON-repair fallback ladder, usage normalization, and a multi-provider rate card
  + cost estimator.
- **Document-prep toolkit** (`pypdf` split/select/merge, `pymupdf` primary + `pdfium2` fallback
  for PDF→image, `Pillow` compress/resize to caps) with base64-size accounting and golden tests.
- Vendored `itemized_bills` schema + a de-tuned, model-neutral prompt under `tasks/`.
- Vertical slice: run `itemized_bills` on a sample PDF with one Gemini Vertex model through the
  gateway and persist a full `run_result`.

## Quickstart

```bash
# 1. Create the environment (uv recommended)
uv venv && uv pip install -e ".[dev]"
#   or: python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

# 2. Run the offline test suite (no creds / no network required)
uv run pytest backend/tests -m "not live"

# 3. Bring up infra and apply migrations
docker compose up -d
cp .env.example .env   # then fill GOOGLE_APPLICATION_CREDENTIALS / VERTEXAI_PROJECT
uv run alembic upgrade head
uv run python scripts/seed_prompts.py

# 4. Run the vertical slice (needs Vertex creds; persists a run_result)
uv run python -m app.runner.vertical_slice data/02B-2026-006427.pdf
```

## FastAPI + React

Apply migrations, then start the internal API on loopback from the repository root:

```bash
uv run uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8100
# Equivalent from backend/: uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8100
```

API health and OpenAPI are available at `http://127.0.0.1:8100/api/health` and
`http://127.0.0.1:8100/openapi.json`. For frontend development, run `npm install && npm run dev`
from `frontend/`; the API allows the Vite origins on ports 5173. To serve the built frontend
from FastAPI, run `npm run build` first and restart uvicorn.

The previous `streamlit_app.py` remains available as a legacy fallback; FastAPI + React is
the primary interface.

## Running the live Gemini slice as a test

```bash
# Will run only if Vertex creds resolve; otherwise it is skipped.
uv run pytest backend/tests -m live
```

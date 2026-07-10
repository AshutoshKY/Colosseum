# 09 — Verification & Rollout

> For the integrating agent (or the last workstream to land). Prerequisites: all of
> `00`–`08`. This doc defines how we prove the product meets the user's asks, the order
> things land, and the known risks.

## 0. STATUS (independently verified 2026-07-10)

All six workstreams are implemented in the working tree (nothing committed yet). Verified:
backend 78 tests passed / 3 live-deselected, ruff clean; frontend 4 tests + eslint + prod
build; alembic 0003→0006 upgrade clean on Postgres; prompt seed idempotent (28 → 0);
API boots with 21 OpenAPI paths, `/api/packs` returns OPD(15)/IPD(13)/IPD-PP(12) with
dependency graphs; `gemini-3.1-pro` enabled+verified (live check passed).

**Outstanding — blocked on external access, in order:**
1. Put a fresh `AWS_BEARER_TOKEN_BEDROCK` in `.env` (expires ~12h) → run
   `uv run python scripts/verify_bedrock.py` → enable verified models in
   `catalog/bedrock.yaml` (currently all gated: 0 enabled).
2. Qwen3-VL endpoint `http://15.252.27.168:8000` is unreachable from this machine
   (connection timeout — possibly VPN/firewall). Once reachable:
   `uv run python scripts/verify_model.py --model qwen3-vl-8b` → flip `enabled/verified`.
3. Run the §3 end-to-end acceptance scenario with ≥3 providers (blocked on 1 and 2;
   a Vertex-only variant can be run today).
4. Optional cleanup: `runner/engine.py` still carries the interim `OPD_DEPENDS` /
   `OPD_GOLD_KEYS` maps — now dead fallback (OPD tasks carry their own `depends_on`);
   safe to delete per the `TODO(WS-C)` marker.
5. Nothing is committed — 55+ new/modified files on `main`.

## 1. Landing order & integration checkpoints

1. **WS A (engine/DB)** + **WS B (providers)** + **WS C (task packs)** in parallel.
   - Checkpoint α (A+B): engine smoke (`python -m app.runner.engine --smoke`) runs 2 docs ×
     {gemini-2.5-flash-lite, qwen3-vl-8b} × segregation+itemized in parallel; DB rows +
     scoreboard correct; a Bedrock model callable via `scripts/verify_bedrock.py`.
   - Checkpoint β (A+C): OPD subset run segregation+audit with `upstream_mode=gold` on a
     gold-complete doc; IPD smoke segregation+itemized on 1 doc.
2. **WS D (judge)** and **WS E (API)** after A.
   - Checkpoint γ: `POST /api/runs` → SSE → `GET results` → `POST judge` end-to-end via curl.
3. **WS F (frontend)** after E (mock-driven work may start immediately).
   - Checkpoint δ: full UI flow against real API.
4. Run `scripts/seed_prompts.py`; update `README.md` (new quickstart: docker-compose up,
   alembic upgrade, seed, uvicorn, frontend); mark Streamlit as legacy in README (do not
   modify the app itself).

Each workstream merges only with: `uv run ruff check backend` clean,
`uv run pytest backend/tests -x -q` green (offline), its doc's acceptance criteria checked
off in the PR description.

## 2. Test additions (summary of per-WS suites)

| Suite | Covers |
|---|---|
| `test_run_spec.py` | RunSpec validation incl. gold pre-flight |
| `test_engine.py` | DAG layering, parallelism (fake gateway, overlap assertions), per-provider semaphores, cancellation, missing-upstream failure isolation |
| `test_upstream.py` | gold vs live resolution, legacy aliases, error messages |
| `test_prompt_store.py` | precedence (override > DB active > constant), seed idempotency |
| `test_ipd_tasks.py` / `test_opd_parity.py` | prompt verbatim checksums, dependency metadata, deterministic transforms (merge/patient_summary/validation), audit template fill |
| `test_bedrock_catalog.py` / `test_qwen_vl.py` | capability gating + provider kwargs (offline); live marks |
| `test_judge.py` | anonymization/shuffle seeding, mode fallback, persistence shapes, idempotent re-judge, bounded concurrency |
| `test_api_*.py` | every router; SSE ordering + replay; multipart dedupe; dry-run errors; openapi validity |
| frontend vitest + Playwright | RunSpec assembly, dependency-graph gold chips, SSE fallback, E2E happy path (mocked) |

Live tests are opt-in: `uv run pytest -m live` (needs docker Postgres + Vertex creds +
fresh Bedrock token + reachable vLLM endpoint).

## 3. End-to-end acceptance scenario (the user's literal ask)

Run this manually before calling the product done:

1. `docker-compose up -d` → `uv run alembic upgrade head` → `uv run python
   scripts/seed_prompts.py` → API on :8100 → frontend (dev or built).
2. **Bulk upload**: drag-drop 20–30 claim PDFs (reuse `test-docs/` copies if needed).
3. **Subset**: pack OPD; select ONLY segregation + audit. UI shows audit's unselected
   upstream deps as "fed from gold"; dry-run flags every document lacking the needed gold
   keys; fix one via the gold editor to prove the loop.
4. **Models**: select ≥3 across providers — a Vertex Gemini, a Bedrock model, and
   `qwen3-vl-8b`. Edit the audit prompt as a per-run override.
5. **Launch**: watch the live grid — cells from different models/docs progress
   concurrently; per-provider caps observed (Vertex ≤4 in flight); cancel+relaunch works.
6. **Results**: leaderboard ranks models; field breakdown shows weak fields; side-by-side
   shows outputs vs gold with mismatch highlighting and the exact prompts used (override
   visible).
7. **Judge**: run gemini-3.1-pro with all 3 modes; per-field verdicts + explanations
   (mode 1), doc-grounded grading for a no-gold doc (mode 2), head-to-head ranking table
   (mode 3). Judge cost visible.
8. **IPD**: repeat a small version (5 docs, segregation+itemized_bills+merge+audit,
   2 models) with pack IPD; per-agent defaults show the healthpay reference params
   (audit = gemini-3.1-pro, thinking medium, max_output 16000).

Product is DONE when all 8 steps pass.

## 4. Ops / env rollout

- `.env` additions (real values, never committed): `AWS_BEARER_TOKEN_BEDROCK`,
  `AWS_REGION_NAME=ap-south-1`, `QWEN_VL_BASE_URL`, `QWEN_VL_API_KEY`. `.env.example`
  documents all with the Bedrock expiry/refresh note.
- Bedrock token expires ~12h: refresh procedure documented in `.env.example` and surfaced
  in-product (verify endpoint returns the expired-token message).
- Gemini 3.1 Pro runs on the superclaims-ai Vertex project via `EXTERNAL_ENV_FILES`
  layering; if that project's creds rotate, re-run `scripts/verify_model.py`.
- docker-compose unchanged (Postgres :5433); alembic migrations 0003–0006 are additive —
  safe on the existing DB.

## 5. Risks & mitigations (consolidated)

| Risk | Mitigation |
|---|---|
| Bedrock bearer token expiry (~12h) | explicit ProviderAuthError message; verify script; never cached in code |
| Gemini 3.x access tied to superclaims project | verify before judge relies on it; judge falls back to gemini-2.5-pro via config |
| vLLM endpoint (15.252.27.168) unreachable/restarted | catalog `verified` flag + verify endpoint; engine records failures per cell, run continues |
| Structured-output vs healthpay json_repair/continuation fidelity | prompts verbatim; difference documented in `tasks/ipd.py`; watch MAX_TOKENS truncation on bill-heavy docs → raise max_output_tokens |
| 8B VL model weak JSON compliance | `needs_repair_fallback: true`; expect lower valid% — that's a benchmark finding, not a bug |
| Vertex rate limits under real parallelism | per-provider semaphores + jittered backoff; defaults conservative (4) |
| Single-process RunManager (no Temporal/Redis) | DB cell status is source of truth; SSE degrades to polling after restart; documented limitation — Temporal remains future work |
| Cost blowups on bulk runs | dry-run cost estimate in UI; live tests pinned to flash-lite; `--full`-style confirmation for >100 cells in the API (422 unless `"confirm_large": true` in spec — add to RunSpec as optional field) |
| Judge judging its own family (Gemini judging Gemini) | logged + stored `judge_is_candidate`; user-visible note in Judge tab |

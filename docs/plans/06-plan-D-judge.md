# 06 — Workstream D: LLM-as-Judge (Gemini 3.1 Pro, 3 modes)

> Prerequisites: `00-master-plan.md` (§6.1 judge config, §6.5 DB), `01-context-colosseum.md`
> §3–6. Depends on: WS A's migration 0005 (`JudgeComparison` table, `models/judge.py`) and
> WS B's `gemini-3.1-pro` enablement (fallback: `gemini-2.5-pro`). Judge calls go through
> the existing `ModelGateway.structured()` like any other model call.

## Goal

`backend/app/scoring/judge.py`: evaluate a completed run's results with an LLM judge in
three modes, persist verdicts, expose a programmatic API (`judge_run`) used by the engine
(auto-judge when `spec.judge.enabled`), the FastAPI route (`POST /api/runs/{id}/judge`),
and a CLI.

## The three modes

### Mode 1 — `gold_grade` (grade vs ground truth)
For every RunResult of the run (per document × model × task) that has gold for its task:
judge sees the task description, the gold JSON, and the model's parsed_output → returns
per-field verdicts with explanations and an overall 0–1 score. This complements the
deterministic `field_metrics` (which is exact-match-oriented) by judging semantic
equivalence ("Apollo Hosp." vs "Apollo Hospital"), and explains WHY fields mismatch.

### Mode 2 — `doc_grade` (grade vs source PDF, no gold needed)
Judge sees the source document pages (same pages the task saw — reuse the task's
page-range logic) plus the model's parsed_output and the task's objective → rubric-scored
0–1 on: faithfulness (no hallucinated values), completeness (nothing present in the doc
missed), format/schema sanity. Requires a document-capable judge (gemini-3.1-pro is
pdf_native). Used when gold is absent — the run-level entrypoint picks `doc_grade`
automatically for docs without gold when the caller requested `gold_grade` (record
`mode_used`).

### Mode 3 — `head_to_head` (ranking across models)
Per (document × task): judge sees the gold if available (else the source pages) and ALL
models' outputs, **anonymized** as "Candidate A/B/C…" with candidate order **shuffled per
document** (seeded by run_id+document_id for reproducibility) → returns a strict ranking +
per-candidate strengths/weaknesses + confidence. De-anonymize before persisting.
Bias controls: candidate labels never include model names; identical outputs must tie;
judge model excluded from candidates it judges is NOT enforced (judge may be among the
benchmarked models) but a warning is logged and stored in the payload
(`judge_is_candidate: true`).

## Structured schemas (judge outputs — `backend/app/scoring/judge_schemas.py`)

```python
class FieldVerdict(BaseModel):
    field_path: str            # "bills[0].items[2].amount"
    verdict: Literal["match", "acceptable_variant", "mismatch", "missing", "hallucinated"]
    explanation: str
    gold_value: str | None
    predicted_value: str | None

class JudgeGradeOutput(BaseModel):     # modes 1 & 2
    overall_score: float               # 0..1
    field_verdicts: list[FieldVerdict] # mode 2: doc-grounded findings instead of gold diffs
    summary: str

class CandidateRank(BaseModel):
    candidate: str                     # "A"…; de-anonymized to model_id at persist time
    rank: int                          # 1 = best; ties allowed
    strengths: str
    weaknesses: str

class JudgeRankingOutput(BaseModel):   # mode 3
    ranking: list[CandidateRank]
    rationale: str
    confidence: Literal["low", "medium", "high"]
```

## Prompts (`backend/app/scoring/judge_prompts.py`)

One system prompt per mode. Requirements: state the judge's role (senior claims-QA
auditor), the task's objective (1-line description added per task — small dict
`TASK_DESCRIPTIONS` in this file for all OPD+IPD task names), explicit scoring rubric,
instruction to penalize hallucinated values hardest, to treat formatting-only differences
as `acceptable_variant`, and (mode 3) to rank strictly with ties only for
indistinguishable quality. Instructions render gold/predicted JSON pretty-printed and
truncated at ~50k chars each with a note when truncated.

## Entrypoints

```python
async def judge_run(run_id: int, cfg: JudgeConfig, *, concurrency: int = 4) -> JudgeSummary
# JudgeConfig = spec.judge shape: {model_id, modes}
```

- Iterates the run's succeeded results; builds judge calls; executes with
  `asyncio.gather` under a semaphore (default 4 — judge model is expensive).
- Persistence: modes 1/2 → `Score.judge_score` JSONB on the result's Score row
  (`{mode, model, overall_score, field_verdicts, summary, cost_usd, judged_at}` — upsert
  Score if scoring hasn't run). Mode 3 → one `JudgeComparison` row per (document, task)
  with de-anonymized payload `{ranking:[{model_id, rank, strengths, weaknesses}],
  rationale, confidence, shuffle_seed, judge_is_candidate}`.
- Judge calls recorded like normal gateway calls (tokens/cost) and the aggregate judge
  cost returned in `JudgeSummary` + surfaced by the leaderboard endpoint.
- CLI: `python -m app.scoring.judge --run 12 --modes gold_grade,head_to_head
  --model gemini-3.1-pro`.
- Config: judge default model in `core/config.py` (`judge_default_model:
  str = "gemini-3.1-pro"`, fallback env-overridable to `gemini-2.5-pro` if 3.1 not
  verified).

## Leaderboard integration (consumed by WS E `GET /runs/{id}/leaderboard`)

Add `scoring/report.py::judge_aggregates(run_id)` → per (task, model): mean judge score
(modes 1/2), mean rank + win rate (mode 3), judged-cell count. Do not change the composite
formula; judge columns are additive.

## Files

| File | Action |
|---|---|
| `backend/app/scoring/judge.py` | NEW — orchestration, anonymization, persistence |
| `backend/app/scoring/judge_schemas.py` | NEW |
| `backend/app/scoring/judge_prompts.py` | NEW (incl. TASK_DESCRIPTIONS) |
| `backend/app/scoring/report.py` | add `judge_aggregates` |
| `backend/app/core/config.py` | `judge_default_model` setting |
| `backend/tests/test_judge.py` | NEW — fake-gateway tests |

## Acceptance criteria

1. Fake-gateway unit tests: anonymization + shuffle is seeded/reproducible and
   de-anonymization correct; docs without gold fall back gold_grade→doc_grade with
   `mode_used` recorded; ties allowed; persistence shapes exactly as above; judge cost
   aggregated.
2. Concurrency bounded (≤4 in-flight, asserted with fake gateway).
3. Idempotent re-judge: re-running overwrites prior judge_score / JudgeComparison for the
   same (run, mode) rather than duplicating.
4. CLI works end-to-end against a seeded SQLite run fixture.
5. Live smoke (after WS B): judge 1 document × 2 models × segregation with
   `gold_grade` + `head_to_head` on a real run; verdicts sane and stored.
6. ruff + full pytest green.

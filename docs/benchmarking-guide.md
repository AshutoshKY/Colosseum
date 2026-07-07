# Colosseum — Benchmarking Guide (run · check · compare)

> The one-page operating manual: how to load ground truth, run any subset of the OPD task
> pack across models, where every byte is stored, and how to compare models durably.
> Companions: [plan.md](./plan.md), [ground-truth-format.md](./ground-truth-format.md),
> [models-and-caveats.md](./models-and-caveats.md).

---

## 0. Prerequisites (one-time per machine)

```bash
docker compose up -d postgres      # Postgres on localhost:5433 (colosseum/colosseum)
uv run alembic upgrade head        # apply migrations
uv run pytest -m "not live"        # offline suite must be green (50 tests)
```

Credentials: `.env` (gitignored) already points `GOOGLE_APPLICATION_CREDENTIALS` at
`secrets/vertex-sa.json`, project `vertex-internal-testing`, plus Langfuse keys.

---

## 1. Ground truth (the golden data)

Human-reviewed production adjudications are the accuracy baseline. Pipeline:

```bash
# 1. Export from the healthpay DBs (run against the right environment):
psql "$HEALTHPAY_FHPL_DATABASE_URL" -tA -f scripts/export_gold_healthpay_fhpl.sql > healthpay_fhpl_gold.jsonl   # numeric claims (test-fhpl branch)
psql "$HEALTHPAY_DATABASE_URL"      -tA -f scripts/export_gold_healthpay.sql      > healthpay_gold.jsonl        # REQ*/alpha claims
psql "$SUPERCLAIMS_DATABASE_URL"    -tA -f scripts/export_gold_superclaims.sql    > superclaims_gold.jsonl      # fallback source

# 2. Convert exports -> per-claim gold JSON (prefers human-corrected edited_payload):
uv run python scripts/convert_gold_exports.py data/gold_exports/*.csv --out data/gold

# 3. Import into the ground_truth table (upserts; re-run any time):
uv run python -m app.scoring.ground_truth_import data/gold/
```

What gets stored per document (22 claims currently):

| ground_truth.task     | gold content                                                | scored? |
|-----------------------|-------------------------------------------------------------|---------|
| `segregation`         | document segments (type + page ranges)                      | yes |
| `itemized_bills`      | production bills, pruned to the ItemizedBillsOutput schema  | yes |
| `items_categorisation`| bill_id + s.no. + category per item                         | yes |
| `nme_analysis`        | human-corrected NME list (from review `edited_payload`)     | yes |
| `audit`               | human-corrected audit analysis (flat AuditAnalysisOutput)   | yes |
| `policy_extraction`   | policy rules + NME items as lists (non-FHPL claims only)    | yes |
| `upstream_bills`      | merged categorised bills — **context only**, feeds dependent tasks | no |
| `upstream_benefits`   | benefit-plan catalog (ids, names, required docs) — **context only** for benefit_plan | no |

`upstream_bills` is the key to isolated task testing: when a task depends on another agent's
output, the runner can feed it this golden data instead of a live model's output.

---

## 2. Running benchmarks

Everything goes through one entrypoint:

```bash
uv run python -m app.runner.opd_smoke [flags]
```

| Flag | Meaning |
|---|---|
| `--docs N` | first N PDFs from `test-docs/` (default 2 — cost-controlled smoke) |
| `--docs-from-gold` | run only on documents that have ground truth |
| `--full` | ALL matched documents (explicit opt-in; costs money) |
| `--model <id>` | add a model (repeatable). Gemini 2.5 Flash is always included as reference |
| `--models-from-enabled` | every registry-enabled model (currently 5, see §4) |
| `--tasks a,b,c` | run only these tasks live (default: all 8) |
| `--gold-upstream` | dependent tasks consume **golden** upstream data (see below) |
| `--pause 2` | seconds between calls — cushion for Vertex per-minute quotas (429s) |
| `--db-url ...` | e.g. `sqlite:///bench.db` for a throwaway DB |

### Task dependency map (what `--gold-upstream` replaces)

```
segregation ─┐
itemized_bills ─┬─ merge_bills ─→ items_categorisation ─→ nme_analysis
consolidated_bills ┘                    │                     │
                                        └──→ benefit_plan ←───┘  (+ policy_extraction context)
merged bills + claimed amount ─────────────→ audit
```

Without `--gold-upstream`, each downstream task consumes the same model's live upstream
output (end-to-end mode — errors compound, like production). With `--gold-upstream`,
audit gets the gold merged bills + gold claimed amount; categorisation/NME/benefit_plan
get gold bills, gold categories, and gold policy rules (isolated mode — measures each
task alone, which is the right way to compare models per task).

### Recipes

```bash
# The standard model comparison (what we run): 3 doc tasks, all gold docs, gold upstream
uv run python -m app.runner.opd_smoke --full --docs-from-gold --gold-upstream --pause 2 \
  --tasks segregation,itemized_bills,audit \
  --model vertex_ai/gemini-2.5-pro --model vertex_ai/gemini-2.5-flash-lite

# Text tasks only (cheap, fast — no PDFs sent):
uv run python -m app.runner.opd_smoke --full --docs-from-gold --gold-upstream \
  --tasks items_categorisation,nme_analysis --models-from-enabled

# Quick 2-doc end-to-end smoke (no gold, validity+cost only):
uv run python -m app.runner.opd_smoke --docs 2

# Everything, every enabled model, end-to-end (expensive — explicit opt-in):
uv run python -m app.runner.opd_smoke --full --models-from-enabled
```

---

## 3. Where everything is stored & how to compare

All state lives in Postgres (`localhost:5433`, db/user/pass `colosseum`).

| Table | Contents |
|---|---|
| `benchmark_run` | one row per invocation (id, name like `opd-smoke:full`, timestamp) |
| `run_cell` | one row per (run × task × document × model), with status/skip_reason |
| `run_result` | **everything**: prompt, raw + parsed output, valid flag, input/output/thinking/cached tokens, per-class cost in USD, latency, retries, error |
| `ground_truth` | gold JSON per (document, task) |
| `score` | persisted accuracy per result: `field_metrics` JSON + `composite` (= accuracy) |
| `document_sample` | registered PDFs (path, sha256, page count) |

### The comparison command

```bash
uv run python -m app.scoring.report                    # score + report the LATEST run
uv run python -m app.scoring.report --run 5            # a specific run
uv run python -m app.scoring.report --run 4 --run 5    # merge runs into one comparison
uv run python -m app.scoring.report --markdown reports/gemini-comparison.md
uv run python -m app.scoring.report --run 5 --fields itemized_bills   # per-field parameter audit
```

`--fields <task>` prints the **per-field match rate** per model — every output parameter
individually (e.g. `bills[].bill.invoice_number`, `bills[].bill.net_amount`,
`bills[].items[].discount`, `bills[].items[].final_amount`, `icd_codes[].code`), so you can
see exactly which parameters a model gets right or wrong, not just one accuracy number.
Field-level mismatch examples (predicted vs gold values, with the exact path) are stored in
`score.field_metrics -> 'mismatches'` for drill-down.

It (1) recomputes field-metric accuracy for every persisted result against ground truth and
upserts it into the `score` table (durable, re-runnable — e.g. after improving the gold),
then (2) prints a per-task markdown matrix:

```
## itemized_bills
| model | docs | valid | mean accuracy | total cost (USD) | median latency | out+think tokens |
```

Accuracy semantics ([field_metrics.py](../backend/app/scoring/field_metrics.py)): scalars
exact (case/space-insensitive), numbers within 1% tolerance, lists as set precision/recall
on the identifying field, `accuracy = matched_gold_leaves / total_gold_leaves`.

### Handy SQL

```sql
-- runs overview
SELECT br.id, br.name, br.created_at, count(rc.id) cells
FROM benchmark_run br LEFT JOIN run_cell rc ON rc.run_id = br.id GROUP BY br.id ORDER BY br.id;

-- per-cell detail for a run (tokens, cost, latency, accuracy)
SELECT rc.task, rc.model_id, ds.path, rr.valid, s.composite AS accuracy,
       rr.total_cost_usd, rr.latency_ms, rr.thinking_tokens
FROM run_cell rc
JOIN run_result rr ON rr.cell_id = rc.id
JOIN document_sample ds ON ds.id = rc.document_id
LEFT JOIN score s ON s.result_id = rr.id
WHERE rc.run_id = :run_id ORDER BY rc.task, rc.model_id;

-- side-by-side outputs for one document + task
SELECT rc.model_id, rr.parsed_output
FROM run_cell rc JOIN run_result rr ON rr.cell_id = rc.id
WHERE rc.run_id = :run_id AND rc.task = 'audit'
  AND rc.document_id = (SELECT id FROM document_sample WHERE path LIKE '%REQTWKX8N5C%');
```

Raw run logs from background executions land in the session scratchpad
(`gold_run.log` etc.); the DB is the source of truth.

---

## 4. Models

77 models across 10 families are registered in
[backend/app/providers/catalog/](../backend/app/providers/catalog/) (Gemini, Grok, Qwen,
Kimi, DeepSeek, GLM, Claude, Mistral, Llama, open models). Only verified-callable models
are `enabled`:

| model_id | modality | notes |
|---|---|---|
| `vertex_ai/gemini-2.5-flash` | PDF-native | default reference model |
| `vertex_ai/gemini-2.5-pro` | PDF-native | strongest / most expensive |
| `vertex_ai/gemini-2.5-flash-lite` | PDF-native | cheapest; watch 429 rate limits (`--pause`) |
| `vertex_ai/qwen/qwen3-235b-a22b-instruct-2507-maas` | text-only | text tasks only (auto-gated) |
| `vertex_ai/deepseek-ai/deepseek-r1-0528-maas` | text-only | text tasks only (auto-gated) |

Text-only models are automatically skipped for document tasks and recorded as
"not applicable" — never as failures. The other 72 models are registered
`enabled=false` with a reason (no API key / not enabled on the Vertex project); flipping
one on = provide the key/enablement and set `enabled: true` in its catalog YAML.

List them any time:

```bash
uv run python -c "
from app.providers.registry import list_models
for c in list_models(enabled_only=True): print(c.model_id, sorted(m.value for m in c.modalities))"
```

---

## 5. Standard workflow (TL;DR)

```bash
docker compose up -d postgres && uv run alembic upgrade head          # infra
uv run python scripts/convert_gold_exports.py data/gold_exports/*.csv --out data/gold
uv run python -m app.scoring.ground_truth_import data/gold/           # gold
uv run python -m app.runner.opd_smoke --full --docs-from-gold --gold-upstream --pause 2 \
  --tasks segregation,itemized_bills,audit \
  --model vertex_ai/gemini-2.5-pro --model vertex_ai/gemini-2.5-flash-lite   # run
uv run python -m app.scoring.report --markdown reports/latest.md      # score + compare
```

Gotchas:
- **429 RESOURCE_EXHAUSTED**: Vertex per-minute quota. Symptoms: `valid=true` but empty
  output (`{"bills": []}`) or `valid=false` with retries — accuracy 0 that is NOT the
  model's fault. Use `--pause 2`+ and re-run the affected model.
- Re-importing gold upserts; re-running `app.scoring.report` re-scores old runs against
  the new gold.
- The full matrix always stays behind explicit flags (`--full`) to control spend.

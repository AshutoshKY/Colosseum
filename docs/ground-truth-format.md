# Colosseum — Ground-Truth / Baseline Format

> How to hand over baseline adjudication data so Colosseum can score model **accuracy /
> precision / recall** per task. Companion: [plan.md](./plan.md),
> [phase-2-opd-and-models.md](./phase-2-opd-and-models.md).

Ground truth is **per document, per task**: for each claim PDF, the gold (correct) structured
output of each OPD task. The importer loads it into the `ground_truth` table; the field-metrics
scorer (`scoring/field_metrics.py`) then diffs each model's parsed output against the gold and
the scoreboard ranks by accuracy (falling back to validity + cost + latency where no gold
exists).

## File shape

A single JSON file (or a directory of them — one per claim). One object, or a list of objects:

```json
{
  "document": "test-docs/REQ65CYP9E0_1.pdf",
  "tasks": {
    "segregation": {
      "segments": [
        { "document_type": "itemized_bill", "pages": "1-2" },
        { "document_type": "prescription",  "pages": "3" }
      ]
    },
    "consolidated_bills": {
      "bills": [
        { "bill": { "invoice_number": "INV-1", "net_amount": 5300.0 },
          "items": [ { "item_name": "Pharmacy", "final_amount": 3668.8 } ] }
      ]
    },
    "items_categorisation": {
      "bill_item_categories": [
        { "bill_id": "INV-1",
          "categorized_items": [ { "s.no.": 1, "category": "Medicines Supplied By Hospital" } ] }
      ]
    },
    "nme_analysis": {
      "nme_list": [
        { "nme_item": { "sr.no": 5, "item_name": "Registration Charges",
                        "bill_amount": 200.0, "deduction_reason": "Administrative: Not Payable" } }
      ],
      "policy_violations": []
    },
    "audit": {
      "original_claimed_amount": 5300.0,
      "true_total_of_bills": 5300.0,
      "status": "MATCH",
      "policy_violations": [],
      "icd_codes": [ { "code": "J06.9", "type": "primary" } ],
      "patches": []
    }
  }
}
```

- **`document`** — either the path of a PDF (resolved/registered against `document_sample`) or
  the document's `sha256` if it is already registered.
- **`tasks`** — a map of `task_name -> gold JSON`. Each gold JSON must match that task's
  Pydantic schema (the same schema the models emit). You only need to provide the tasks you
  have a baseline for; missing tasks fall back to validity-only scoring.

Any task name returned by `GET /api/packs` is accepted. Values use the same JSON shape as
the task's output schema. This includes all OPD clinical, bill, identity, ICD,
patient-summary and benefit tasks, plus all IPD extraction, merge, NME, audit and validation
tasks.

For subset runs, unselected upstream task outputs are read from this same `tasks` map.
Legacy aliases remain accepted: `upstream_bills` maps to `merge_bills` and
`upstream_benefits` supplies benefit context. Context-only keys `claimed_amount`, `policy`,
`benefits`, and `patient_name` are feedable but never scored.

## How fields are scored

`scoring/field_metrics.py` walks the **gold** as the reference field set:

- **Scalars** — exact match (strings are trimmed + case-insensitive).
- **Numbers** (amounts) — match within a 1% relative tolerance (mirrors the audit decimal
  tolerance), so `1000.0` vs `1005.0` counts as correct.
- **Lists** (bill items, NME items, ICD codes, segments) — set-based **precision/recall** using
  the most identifying field (`item_name` / `description` / `code` / `rule_name` /
  `document_type`). Reported per list path plus rolled into overall accuracy as recall.
- A **null/invalid** prediction scores 0 against the gold (not undefined).

Overall `accuracy = matched_leaves / total_gold_leaves`.

## Importing

```bash
# single file
uv run python -m app.scoring.ground_truth_import path/to/gold.json

# a directory of per-claim gold files
uv run python -m app.scoring.ground_truth_import path/to/gold_dir/

# override the DB (e.g. local sqlite)
uv run python -m app.scoring.ground_truth_import gold.json --db-url sqlite:///gt.db
```

Re-importing the same `(document, task)` **upserts** (updates the gold in place), so you can
correct a baseline and re-run without duplicates. The importer prints
`{"inserted": N, "updated": M, "files": K}`.

Once gold is loaded, re-run the OPD smoke (or the full matrix); the scoreboard's `accuracy`
column is populated for every `(document, task)` that has a baseline, and ranking shifts to
accuracy-first.

"""Score persistence + model-comparison report.

The smoke runner prints a scoreboard but the accuracy numbers were derived in memory. This
module makes comparisons durable and repeatable:

1. ``score_run`` recomputes field-metric accuracy for every persisted ``run_result`` against
   the ``ground_truth`` table and UPSERTS one ``score`` row per result (field_metrics JSON +
   composite = accuracy). Safe to re-run any time (e.g. after importing better gold).
2. ``comparison`` aggregates per (task, model): docs, valid%, mean accuracy, cost, latency,
   tokens — the durable model-vs-model view.

CLI:
    uv run python -m app.scoring.report                 # score + report the latest run
    uv run python -m app.scoring.report --run 5         # a specific run
    uv run python -m app.scoring.report --run 4 --run 5 # merge several runs
    uv run python -m app.scoring.report --markdown out.md
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.db import get_engine, session_scope
from app.models import BenchmarkRun, GroundTruth, RunCell, RunResult, Score
from app.scoring.field_metrics import score_against_gold

logger = get_logger(__name__)

# Context-only ground-truth entries (upstream feed data) that are never scored.
NON_SCORED_TASKS = {"upstream_bills", "upstream_benefits"}


def _gold_map(session: Session) -> dict[tuple[int, str], dict]:
    rows = session.exec(select(GroundTruth)).all()
    return {(g.document_id, g.task): g.gold for g in rows}


def score_run(session: Session, run_id: int) -> int:
    """Compute + upsert a ``score`` row for every result of the run. Returns rows scored."""
    gold_map = _gold_map(session)
    pairs = session.exec(
        select(RunResult, RunCell).join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run_id)
    ).all()
    scored = 0
    for result, cell in pairs:
        gold = gold_map.get((cell.document_id, cell.task))
        if gold is None or cell.task in NON_SCORED_TASKS:
            continue
        metrics = score_against_gold(result.parsed_output, gold)
        existing = session.exec(select(Score).where(Score.result_id == result.id)).first()
        if existing:
            existing.field_metrics = metrics.as_dict()
            existing.composite = metrics.accuracy
            session.add(existing)
        else:
            session.add(
                Score(result_id=result.id, field_metrics=metrics.as_dict(), composite=metrics.accuracy)
            )
        scored += 1
    return scored


@dataclass
class Aggregate:
    task: str
    model_id: str
    accuracies: list[float] = field(default_factory=list)
    valid: int = 0
    skipped: int = 0
    cells: int = 0
    cost: float = 0.0
    latencies: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def mean_accuracy(self) -> float | None:
        return round(statistics.mean(self.accuracies), 4) if self.accuracies else None

    @property
    def median_latency_ms(self) -> int | None:
        return int(statistics.median(self.latencies)) if self.latencies else None


def comparison(session: Session, run_ids: list[int]) -> dict[str, list[Aggregate]]:
    """Per-task aggregates keyed (task, model), merged across the given runs."""
    gold_map = _gold_map(session)
    aggs: dict[tuple[str, str], Aggregate] = {}
    for run_id in run_ids:
        pairs = session.exec(
            select(RunResult, RunCell).join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
            .where(RunCell.run_id == run_id)
        ).all()
        for result, cell in pairs:
            agg = aggs.setdefault((cell.task, cell.model_id), Aggregate(cell.task, cell.model_id))
            agg.cells += 1
            if str(getattr(cell, "status", "")) .endswith("skipped"):
                agg.skipped += 1
                continue
            agg.valid += int(bool(result.valid))
            agg.cost += float(result.total_cost_usd or 0)
            if result.latency_ms:
                agg.latencies.append(result.latency_ms)
            agg.input_tokens += result.input_tokens or 0
            agg.output_tokens += result.output_tokens or 0
            agg.thinking_tokens += result.thinking_tokens or 0
            gold = gold_map.get((cell.document_id, cell.task))
            if gold is not None and cell.task not in NON_SCORED_TASKS:
                agg.accuracies.append(score_against_gold(result.parsed_output, gold).accuracy)

    by_task: dict[str, list[Aggregate]] = {}
    for (task, _), agg in sorted(aggs.items()):
        by_task.setdefault(task, []).append(agg)
    for rows in by_task.values():
        rows.sort(key=lambda a: (-(a.mean_accuracy or -1), a.cost))
    return by_task


def field_breakdown(session: Session, run_ids: list[int], task: str) -> dict[str, dict[str, dict]]:
    """Per-field match rates for one task: {field_path: {model_id: {matched, total}}}.

    Lets you audit every output parameter individually (e.g. bills[].items[].discount,
    bills[].bill.invoice_number, icd_codes[].code) across all documents of the run(s).
    """
    gold_map = _gold_map(session)
    out: dict[str, dict[str, dict]] = {}
    for run_id in run_ids:
        pairs = session.exec(
            select(RunResult, RunCell).join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
            .where(RunCell.run_id == run_id, RunCell.task == task)
        ).all()
        for result, cell in pairs:
            gold = gold_map.get((cell.document_id, cell.task))
            if gold is None:
                continue
            metrics = score_against_gold(result.parsed_output, gold)
            for path, counts in (metrics.details.get("fields") or {}).items():
                slot = out.setdefault(path, {}).setdefault(cell.model_id, {"matched": 0, "total": 0})
                slot["matched"] += counts["matched"]
                slot["total"] += counts["total"]
    return out


def render_field_breakdown(task: str, breakdown: dict[str, dict[str, dict]]) -> str:
    models = sorted({m for per_model in breakdown.values() for m in per_model})
    short = {m: m.rsplit("/", 1)[-1] for m in models}
    lines = [f"## {task} — per-field match rate (matched/total across documents)", ""]
    lines.append("| field | " + " | ".join(short[m] for m in models) + " |")
    lines.append("|---|" + "---|" * len(models))
    for path in sorted(breakdown):
        cells = []
        for m in models:
            c = breakdown[path].get(m)
            cells.append(f"{c['matched']}/{c['total']} ({c['matched']/c['total']:.0%})" if c and c["total"] else "-")
        lines.append(f"| `{path}` | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def render_markdown(by_task: dict[str, list[Aggregate]], run_ids: list[int]) -> str:
    lines = [f"# Model comparison — run(s) {', '.join(map(str, run_ids))}", ""]
    for task, rows in by_task.items():
        lines += [f"## {task}", ""]
        lines.append(
            "| model | docs | valid | mean accuracy | total cost (USD) | median latency | out+think tokens |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for a in rows:
            run_n = a.cells - a.skipped
            acc = f"{a.mean_accuracy:.2%}" if a.mean_accuracy is not None else "n/a"
            valid = f"{a.valid}/{run_n}" if run_n else f"skipped ({a.skipped})"
            lat = f"{a.median_latency_ms / 1000:.1f}s" if a.median_latency_ms else "-"
            lines.append(
                f"| {a.model_id} | {run_n} | {valid} | {acc} | ${a.cost:.4f} | {lat} "
                f"| {a.output_tokens:,}+{a.thinking_tokens:,} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist scores + print model comparison for benchmark runs.")
    parser.add_argument("--run", action="append", type=int, default=[], help="run id (repeatable; default latest)")
    parser.add_argument("--db-url", default=None, help="override DB URL")
    parser.add_argument("--markdown", default=None, help="also write the report to this .md file")
    parser.add_argument("--no-score", action="store_true", help="skip score upserts; report only")
    parser.add_argument(
        "--fields", default=None, metavar="TASK",
        help="also print a per-field match-rate breakdown for this task "
             "(e.g. --fields itemized_bills shows invoice/discount/amount fields per model)",
    )
    args = parser.parse_args(argv)

    engine = get_engine(args.db_url) if args.db_url else get_engine()
    with session_scope(engine) as session:
        run_ids = args.run
        if not run_ids:
            latest = session.exec(select(BenchmarkRun).order_by(BenchmarkRun.id.desc())).first()  # type: ignore[union-attr]
            if latest is None:
                print("no benchmark runs found", file=sys.stderr)
                return 1
            run_ids = [latest.id]
        if not args.no_score:
            for rid in run_ids:
                n = score_run(session, rid)
                print(f"run {rid}: {n} result(s) scored -> score table")
        report = render_markdown(comparison(session, run_ids), run_ids)
        if args.fields:
            report += "\n" + render_field_breakdown(
                args.fields, field_breakdown(session, run_ids, args.fields)
            )

    print()
    print(report)
    if args.markdown:
        from pathlib import Path

        Path(args.markdown).write_text(report, encoding="utf-8")
        print(f"written -> {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

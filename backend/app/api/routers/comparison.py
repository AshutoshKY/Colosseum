"""Leaderboard, field-level, and side-by-side comparison views."""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.api.deps import SessionDep
from app.api.schemas import FieldBreakdownOut, FieldRow, LeaderboardRow, SideBySideOut
from app.models import (
    BenchmarkRun,
    GroundTruth,
    JudgeComparison,
    RunCell,
    RunResult,
    Score,
)
from app.scoring.report import comparison, field_breakdown
from app.scoring.scoreboard import ScoreboardRow, build_scoreboard

router = APIRouter(prefix="/runs", tags=["comparison"])


def _judge_rows(session: Session, run_id: int) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        from app.scoring.report import judge_aggregates
    except ImportError:
        return {}
    parameters = inspect.signature(judge_aggregates).parameters
    data = judge_aggregates(session, run_id) if len(parameters) > 1 else judge_aggregates(run_id)
    output: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(key, tuple) and len(key) == 2:
                output[(str(key[0]), str(key[1]))] = _dict(value)
            elif isinstance(value, list):
                for row in value:
                    item = _dict(row)
                    model = item.get("model_id") or item.get("model")
                    if model:
                        output[(str(key), str(model))] = item
    elif isinstance(data, list):
        for row in data:
            item = _dict(row)
            if item.get("task") and (item.get("model_id") or item.get("model")):
                output[(str(item["task"]), str(item.get("model_id") or item["model"]))] = item
    return output


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    return dict(vars(value))


@router.get("/{run_id}/leaderboard", response_model=list[LeaderboardRow])
def leaderboard(run_id: int, session: SessionDep) -> list[LeaderboardRow]:
    if session.get(BenchmarkRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    aggregates = [row for rows in comparison(session, [run_id]).values() for row in rows]
    scoring = build_scoreboard(
        [
            ScoreboardRow(
                task=row.task,
                model_id=row.model_id,
                valid=bool(row.valid),
                accuracy=row.mean_accuracy,
                total_cost_usd=row.cost,
                latency_ms=row.median_latency_ms or 0,
            )
            for row in aggregates
        ]
    )
    scores = {(row.task, row.model_id): row for row in scoring}
    judges = _judge_rows(session, run_id)
    output: list[LeaderboardRow] = []
    for aggregate in aggregates:
        active_cells = aggregate.cells - aggregate.skipped
        score = scores[(aggregate.task, aggregate.model_id)]
        judge = judges.get((aggregate.task, aggregate.model_id), {})
        output.append(
            LeaderboardRow(
                task=aggregate.task,
                model=aggregate.model_id,
                model_id=aggregate.model_id,
                cells=active_cells,
                valid_percent=aggregate.valid / active_cells if active_cells else 0,
                accuracy=aggregate.mean_accuracy,
                cost_usd=round(aggregate.cost, 8),
                cost_per_doc=round(aggregate.cost / active_cells, 8) if active_cells else 0,
                median_latency_ms=aggregate.median_latency_ms,
                composite=round(score.composite, 4),
                rank=score.rank,
                judge_score=judge.get("judge_score") or judge.get("mean_judge_score"),
                mean_rank=judge.get("mean_rank"),
                win_rate=judge.get("win_rate"),
                judged_cells=judge.get("judged_cells") or judge.get("judged_cell_count"),
            )
        )
    return sorted(output, key=lambda row: (row.task, row.rank or 10**9, row.model_id))


@router.get("/{run_id}/field-breakdown", response_model=FieldBreakdownOut)
def fields(
    run_id: int,
    session: SessionDep,
    task: str = Query(..., min_length=1),
) -> FieldBreakdownOut:
    if session.get(BenchmarkRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    raw = field_breakdown(session, [run_id], task)
    return FieldBreakdownOut(
        task=task,
        fields=[
            FieldRow(
                path=path,
                per_model={
                    model: counts["matched"] / counts["total"] if counts["total"] else 0
                    for model, counts in per_model.items()
                },
            )
            for path, per_model in sorted(raw.items())
        ],
    )


@router.get("/{run_id}/side-by-side", response_model=SideBySideOut)
def side_by_side(
    run_id: int,
    session: SessionDep,
    document_id: int = Query(...),
    task: str = Query(..., min_length=1),
) -> SideBySideOut:
    if session.get(BenchmarkRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    pairs = session.exec(
        select(RunResult, RunCell)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(
            RunCell.run_id == run_id,
            RunCell.document_id == document_id,
            RunCell.task == task,
        )
    ).all()
    result_ids = [result.id for result, _ in pairs if result.id is not None]
    scores = (
        {
            row.result_id: row
            for row in session.exec(select(Score).where(Score.result_id.in_(result_ids))).all()  # type: ignore[union-attr]
        }
        if result_ids
        else {}
    )
    outputs: list[dict[str, Any]] = []
    models: dict[str, dict[str, Any]] = {}
    for result, cell in pairs:
        score = scores.get(result.id)
        score_metrics = score.field_metrics if score else None
        fields = (score_metrics or {}).get("details", {}).get("fields", {})
        field_verdicts = {
            path: "match"
            if counts.get("total", 0) and counts.get("matched", 0) == counts.get("total", 0)
            else "mismatch"
            for path, counts in fields.items()
        }
        item = {
            "model_id": cell.model_id,
            "latency_ms": result.latency_ms,
            "completed_at": result.created_at,
            "parsed_output": result.parsed_output,
            "valid": result.valid,
            "field_metrics": field_verdicts,
            "score": score_metrics,
            "mismatches": {
                path: counts
                for path, counts in fields.items()
                if counts.get("matched", 0) < counts.get("total", 0)
            },
            "judge": score.judge_score if score else None,
            "prompt_system": result.prompt_system,
            "prompt_instruction": result.prompt_instruction,
            "prompt_version": result.prompt_version,
            "raw_response": json.dumps(result.raw_response, indent=2, default=str)
            if result.raw_response is not None
            else None,
        }
        outputs.append(item)
        models[cell.model_id] = item
    gold_row = session.exec(
        select(GroundTruth).where(
            GroundTruth.document_id == document_id,
            GroundTruth.task == task,
        )
    ).first()
    comparisons = session.exec(
        select(JudgeComparison).where(
            JudgeComparison.run_id == run_id,
            JudgeComparison.document_id == document_id,
            JudgeComparison.task_name == task,
        )
    ).all()
    judge = [
        {
            "mode": row.mode,
            "judge_model": row.judge_model,
            "payload": row.payload,
            "rationale": row.rationale,
            "cost_usd": float(row.cost_usd or 0),
        }
        for row in comparisons
    ]
    return SideBySideOut(
        document_id=document_id,
        task=task,
        gold=gold_row.gold if gold_row else None,
        models=models,
        outputs=outputs,
        judge=judge,
    )

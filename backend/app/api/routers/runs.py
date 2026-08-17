"""Run lifecycle, result detail, SSE progress, cancellation, and judging."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session, select

from app.api.deps import RunManagerDep, SessionDep
from app.api.schemas import (
    CellOut,
    CostBreakdownOut,
    CostEstimateOut,
    DryRunOut,
    JudgeJobOut,
    JudgeRequest,
    ResultOut,
    ResultsOut,
    RunCreated,
    RunDetailOut,
    RunOut,
    RunPatch,
)
from app.core.config import get_settings
from app.models import (
    BenchmarkRun,
    DocumentSample,
    JudgeComparison,
    RunCell,
    RunResult,
    RunStatus,
    Score,
)
from app.providers.pricing.estimator import load_rate_card, resolve_pricing_ref
from app.providers.registry import get_capability
from app.runner.engine import _counts, execution_pack
from app.runner.run_manager import RunManager
from app.runner.spec import RunSpec

router = APIRouter(prefix="/runs", tags=["runs"])
_TERMINAL = {"completed", "failed", "cancelled"}
_judge_jobs: dict[int, asyncio.Task[Any]] = {}
_judge_states: dict[int, str] = {}


def _status(value: Any) -> str:
    return value.value if isinstance(value, RunStatus) else str(value)


def _error_message(error: Any) -> str | None:
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error) if error else None


def _run_cost(session: Session, run_id: int) -> float:
    rows = session.exec(
        select(RunResult)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run_id)
    ).all()
    return round(sum(float(row.total_cost_usd or 0) for row in rows), 8)


def _elapsed_ms(started_at: Any, finished_at: Any | None = None) -> int | None:
    if not started_at:
        return None
    start = started_at if getattr(started_at, "tzinfo", None) else started_at.replace(tzinfo=UTC)
    end = finished_at or datetime.now(UTC)
    end = end if getattr(end, "tzinfo", None) else end.replace(tzinfo=UTC)
    return max(0, round((end - start).total_seconds() * 1000))


def _run_out(session: Session, run: BenchmarkRun) -> RunOut:
    assert run.id is not None
    judge_status = _judge_states.get(run.id)
    if judge_status is None:
        comparison_exists = session.exec(
            select(JudgeComparison.id).where(JudgeComparison.run_id == run.id)
        ).first()
        graded = session.exec(
            select(Score)
            .join(RunResult, RunResult.id == Score.result_id)  # type: ignore[arg-type]
            .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
            .where(RunCell.run_id == run.id)
        ).all()
        if comparison_exists is not None or any(score.judge_score for score in graded):
            judge_status = "completed"
    result_times = session.exec(
        select(RunResult.created_at)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run.id)
    ).all()
    finished_at = max(result_times) if result_times and _status(run.status) in _TERMINAL else None
    return RunOut(
        run_id=run.id,
        name=run.name,
        pack=run.pack,
        status=_status(run.status),
        created_at=run.created_at,
        elapsed_ms=_elapsed_ms(run.created_at, finished_at),
        counts=_counts(session, run.id),
        spec=run.spec or {},
        cost_usd=_run_cost(session, run.id),
        judge_status=judge_status,
        failure_reason=_run_failure_reason(session, run.id) if _status(run.status) == "failed" else None,
    )


def _run_failure_reason(session: Session, run_id: int) -> str | None:
    """Return the most useful persisted reason for a failed run."""
    cells = session.exec(select(RunCell).where(RunCell.run_id == run_id)).all()
    results = session.exec(
        select(RunResult)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run_id)
    ).all()
    errors = [_error_message(row.error) for row in results if _error_message(row.error)]
    if errors:
        return errors[0]
    skipped = [cell.skip_reason for cell in cells if cell.skip_reason]
    if skipped:
        return f"No LLM call was made: {skipped[0]}"
    return "The run failed before producing a result. Check backend logs for details."


def _validate_spec(session: Session, spec: RunSpec) -> JSONResponse | None:
    unknown = spec.validate_documents(session)
    if unknown:
        return JSONResponse(status_code=422, content={"unknown_document_ids": unknown})
    missing = spec.validate_gold(session)
    if missing:
        return JSONResponse(
            status_code=422,
            content={"missing_gold": {str(doc_id): keys for doc_id, keys in missing.items()}},
        )
    return None


def _cost_estimate(spec: RunSpec) -> CostEstimateOut:
    card = load_rate_card()
    assumed_input = 10_000
    assumed_output = 2_000
    pack = execution_pack(spec)
    total = 0.0
    priced_cells = 0
    for model_id in spec.model_ids:
        cap = get_capability(model_id)
        pricing_key = resolve_pricing_ref(cap.pricing_ref, card)
        rates = (card.get("models") or {}).get(pricing_key, {}) if pricing_key else {}
        per_cell = (
            assumed_input * float(rates.get("input_usd_per_million", 0))
            + assumed_output * float(rates.get("output_usd_per_million", 0))
        ) / 1_000_000
        llm_tasks = sum(not pack.tasks[name].deterministic for name in spec.selected_tasks)
        cells = len(spec.document_ids) * llm_tasks
        priced_cells += cells
        total += per_cell * cells
    return CostEstimateOut(
        total_usd=round(total, 6),
        assumed_input_tokens_per_cell=assumed_input,
        assumed_output_tokens_per_cell=assumed_output,
        priced_cells=priced_cells,
    )


@router.post("/dry-run", response_model=DryRunOut)
def dry_run(spec: RunSpec, session: SessionDep) -> DryRunOut | JSONResponse:
    invalid = _validate_spec(session, spec)
    if invalid:
        return invalid
    plan = execution_pack(spec).resolve_subset(spec.selected_tasks, spec.upstream_mode)
    return DryRunOut(
        layers=plan.layers,
        gold_requirements={name: list(keys) for name, keys in plan.gold_requirements.items()},
        cost_estimate=_cost_estimate(spec),
    )


@router.post("", response_model=RunCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    spec: RunSpec,
    session: SessionDep,
    manager: RunManagerDep,
) -> RunCreated | JSONResponse:
    invalid = _validate_spec(session, spec)
    if invalid:
        return invalid
    try:
        run_id = await manager.launch(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RunCreated(run_id=run_id, status="running")


@router.get("", response_model=list[RunOut])
def list_runs(
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[RunOut]:
    rows = session.exec(
        select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).offset(offset).limit(limit)  # type: ignore[union-attr]
    ).all()
    return [_run_out(session, run) for run in rows]


def _cell_rows(session: Session, run_id: int) -> list[CellOut]:
    cells = session.exec(select(RunCell).where(RunCell.run_id == run_id)).all()
    documents = {
        row.id: row for row in session.exec(select(DocumentSample)).all() if row.id is not None
    }
    results = session.exec(
        select(RunResult)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run_id)
    ).all()
    by_cell = {row.cell_id: row for row in results}
    return [
        CellOut(
            document_id=cell.document_id,
            document_name=Path(documents[cell.document_id].path).name
            if cell.document_id in documents
            else str(cell.document_id),
            model_id=cell.model_id,
            task=cell.task,
            status=_status(cell.status),
            created_at=cell.created_at,
            completed_at=by_cell[cell.id].created_at if cell.id in by_cell else None,
            latency_ms=by_cell[cell.id].latency_ms if cell.id in by_cell else None,
            cost_usd=float(by_cell[cell.id].total_cost_usd or 0) if cell.id in by_cell else None,
            cost_breakdown=CostBreakdownOut(
                input_usd=float(by_cell[cell.id].est_input_cost or 0),
                output_usd=float(by_cell[cell.id].est_output_cost or 0),
                cache_usd=float(by_cell[cell.id].est_cache_cost or 0),
                thinking_usd=float(by_cell[cell.id].est_thinking_cost or 0),
                total_usd=float(by_cell[cell.id].total_cost_usd or 0),
            )
            if cell.id in by_cell
            else None,
            usage={
                "input_tokens": by_cell[cell.id].input_tokens,
                "output_tokens": by_cell[cell.id].output_tokens,
                "thinking_tokens": by_cell[cell.id].thinking_tokens,
                "cached_tokens": by_cell[cell.id].cached_tokens,
                "total_tokens": by_cell[cell.id].total_tokens,
            }
            if cell.id in by_cell
            else {},
            error=_error_message(by_cell[cell.id].error) if cell.id in by_cell else None,
            skip_reason=cell.skip_reason,
        )
        for cell in cells
    ]


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(run_id: int, session: SessionDep) -> RunDetailOut:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunDetailOut(run=_run_out(session, run), cells=_cell_rows(session, run_id))


def _known_to_manager(manager: RunManager, run_id: int) -> bool:
    checker = getattr(manager, "is_live", None)
    if callable(checker):
        return bool(checker(run_id))
    tasks = getattr(manager, "_tasks", {})
    events = getattr(manager, "_events", {})
    if run_id in tasks or run_id in events:
        return True
    return not isinstance(manager, RunManager)  # fake managers own their subscribe semantics


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str, separators=(',', ':'))}\n\n"


@router.get("/{run_id}/events")
async def run_events(
    run_id: int,
    request: Request,
    session: SessionDep,
    manager: RunManagerDep,
) -> StreamingResponse:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    synthetic = {
        "type": "run",
        "run_id": run_id,
        "status": _status(run.status),
        "counts": _counts(session, run_id),
    }

    async def stream() -> AsyncIterator[str]:
        if not _known_to_manager(manager, run_id):
            yield _sse(synthetic)
            return
        iterator = manager.subscribe(run_id, replay=True)
        pending: asyncio.Task[Any] | None = None
        try:
            while not await request.is_disconnected():
                pending = pending or asyncio.create_task(anext(iterator))
                done, _ = await asyncio.wait({pending}, timeout=15)
                if not done:
                    yield ": heartbeat\n\n"
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    break
                pending = None
                yield _sse(event)
                if event.get("type") == "run" and event.get("status") in _TERMINAL:
                    break
        finally:
            if pending and not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
            closer = getattr(iterator, "aclose", None)
            if closer:
                await closer()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: int,
    session: SessionDep,
    manager: RunManagerDep,
) -> dict[str, str]:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await manager.cancel(run_id)
    try:
        current = manager.status(run_id).status
    except KeyError:
        current = _status(run.status)
    return {"status": current}


@router.patch("/{run_id}", response_model=RunOut)
def rename_run(run_id: int, body: RunPatch, session: SessionDep) -> RunOut:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run.name = body.name.strip()
    session.add(run)
    session.commit()
    session.refresh(run)
    return _run_out(session, run)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: int, session: SessionDep, manager: RunManagerDep) -> None:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if _known_to_manager(manager, run_id):
        await manager.cancel(run_id)
    cell_ids = session.exec(select(RunCell.id).where(RunCell.run_id == run_id)).all()
    if cell_ids:
        result_ids = session.exec(select(RunResult.id).where(RunResult.cell_id.in_(cell_ids))).all()
        if result_ids:
            for score in session.exec(select(Score).where(Score.result_id.in_(result_ids))).all():
                session.delete(score)
            for result in session.exec(select(RunResult).where(RunResult.id.in_(result_ids))).all():
                session.delete(result)
        for cell in session.exec(select(RunCell).where(RunCell.id.in_(cell_ids))).all():
            session.delete(cell)
    for comparison in session.exec(
        select(JudgeComparison).where(JudgeComparison.run_id == run_id)
    ).all():
        session.delete(comparison)
    session.delete(run)
    session.commit()
    _judge_states.pop(run_id, None)


@router.get("/{run_id}/export")
def export_run(
    run_id: int,
    session: SessionDep,
    format: str = Query(default="json", pattern="^(json|csv)$"),
) -> Response:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = results(run_id, session, include_raw=True).results
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in run.name) or f"run-{run_id}"
    if format == "json":
        payload = {
            "run": _run_out(session, run).model_dump(mode="json"),
            "results": [row.model_dump(mode="json") for row in rows],
        }
        return Response(
            content=json.dumps(payload, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "document_id",
            "document_name",
            "model_id",
            "task",
            "status",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "thinking_tokens",
            "total_tokens",
            "input_cost_usd",
            "output_cost_usd",
            "cache_cost_usd",
            "thinking_cost_usd",
            "cost_usd",
            "retries",
            "error",
            "skip_reason",
            "parsed_output",
        ]
    )
    for row in rows:
        cb = row.cost_breakdown or CostBreakdownOut()
        usage = row.usage or {}
        writer.writerow(
            [
                row.document_id,
                row.document_name,
                row.model_id,
                row.task,
                row.status,
                row.latency_ms,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cached_tokens", 0),
                usage.get("thinking_tokens", 0),
                usage.get("total_tokens", 0),
                cb.input_usd,
                cb.output_usd,
                cb.cache_usd,
                cb.thinking_usd,
                row.cost_usd,
                row.retries,
                row.error,
                row.skip_reason,
                json.dumps(row.parsed_output, default=str) if row.parsed_output is not None else "",
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


@router.get("/{run_id}/results", response_model=ResultsOut)
def results(
    run_id: int,
    session: SessionDep,
    include_raw: bool = False,
) -> ResultsOut:
    if session.get(BenchmarkRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    cells = session.exec(select(RunCell).where(RunCell.run_id == run_id)).all()
    documents = {
        row.id: row for row in session.exec(select(DocumentSample)).all() if row.id is not None
    }
    result_rows = session.exec(
        select(RunResult)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run_id)
    ).all()
    by_cell = {row.cell_id: row for row in result_rows}
    scores = {
        row.result_id: row
        for row in session.exec(select(Score)).all()
        if row.result_id in {result.id for result in result_rows}
    }
    output: list[ResultOut] = []
    for cell in cells:
        result = by_cell.get(cell.id)
        score = scores.get(result.id) if result and result.id is not None else None
        output.append(
            ResultOut(
                document_id=cell.document_id,
                document_name=Path(documents[cell.document_id].path).name
                if cell.document_id in documents
                else str(cell.document_id),
                model_id=cell.model_id,
                task=cell.task,
                status=_status(cell.status),
                created_at=cell.created_at,
                completed_at=result.created_at if result else None,
                latency_ms=result.latency_ms if result else None,
                cost_usd=float(result.total_cost_usd or 0) if result else None,
                cost_breakdown=CostBreakdownOut(
                    input_usd=float(result.est_input_cost or 0),
                    output_usd=float(result.est_output_cost or 0),
                    cache_usd=float(result.est_cache_cost or 0),
                    thinking_usd=float(result.est_thinking_cost or 0),
                    total_usd=float(result.total_cost_usd or 0),
                )
                if result
                else None,
                error=_error_message(result.error) if result else None,
                skip_reason=cell.skip_reason,
                result_id=result.id if result else None,
                parsed_output=result.parsed_output if result else None,
                prompt_system=result.prompt_system if result else None,
                prompt_instruction=result.prompt_instruction if result else None,
                prompt_version=result.prompt_version if result else None,
                raw_response=result.raw_response if result and include_raw else None,
                valid=result.valid if result else None,
                usage={
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "thinking_tokens": result.thinking_tokens,
                    "cached_tokens": result.cached_tokens,
                    "total_tokens": result.total_tokens,
                }
                if result
                else {},
                retries=result.retries if result else 0,
                score={"field_metrics": score.field_metrics, "judge_score": score.judge_score}
                if score
                else None,
            )
        )
    return ResultsOut(results=output)


async def _run_judge(run_id: int, payload: dict[str, Any]) -> None:
    _judge_states[run_id] = "running"
    try:
        from app.scoring.judge import judge_run

        await judge_run(run_id, payload)
    except Exception:  # the state is exposed to the client; provider detail is logged by judge
        _judge_states[run_id] = "failed"
        raise
    else:
        _judge_states[run_id] = "completed"


@router.post("/{run_id}/judge", response_model=JudgeJobOut, status_code=202)
async def trigger_judge(
    run_id: int,
    body: JudgeRequest,
    session: SessionDep,
) -> JudgeJobOut:
    run = session.get(BenchmarkRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if _status(run.status) not in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail="Run must finish before judging")
    try:
        from app.scoring.judge import judge_run as _  # noqa: F401
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Judge support is not installed") from exc
    existing = _judge_jobs.get(run_id)
    if existing and not existing.done():
        return JudgeJobOut(run_id=run_id, status="running")
    model_id = body.model_id or get_settings().judge_default_model
    try:
        capability = get_capability(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown judge model: {model_id}") from exc
    if not capability.enabled or not capability.verified:
        raise HTTPException(status_code=422, detail=f"Judge model must be enabled and verified: {model_id}")
    selected_tasks = set(body.task_names or ())
    selected_documents = set(body.document_ids or ())
    cells = session.exec(select(RunCell.task, RunCell.document_id).where(RunCell.run_id == run_id)).all()
    available_tasks = {task for task, _ in cells}
    available_documents = {document_id for _, document_id in cells}
    if unknown_tasks := selected_tasks - available_tasks:
        raise HTTPException(status_code=422, detail=f"Unknown judge tasks: {', '.join(sorted(unknown_tasks))}")
    if unknown_documents := selected_documents - available_documents:
        raise HTTPException(status_code=422, detail=f"Unknown judge documents: {', '.join(map(str, sorted(unknown_documents)))}")
    payload = {
        "model_id": model_id,
        "modes": body.modes,
        "task_names": body.task_names,
        "document_ids": body.document_ids,
    }
    job = asyncio.create_task(_run_judge(run_id, payload), name=f"judge-run-{run_id}")
    _judge_jobs[run_id] = job
    job.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
    return JudgeJobOut(run_id=run_id, status="queued")

"""LLM-as-judge orchestration for gold, document, and head-to-head modes."""

from __future__ import annotations

import argparse
import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from string import ascii_uppercase
from typing import Any

from sqlmodel import Session, select

from app.db import get_engine
from app.models import BenchmarkRun, DocumentSample, GroundTruth, RunCell, RunResult, Score
from app.providers.adapters import DocumentInput
from app.providers.gateway import ModelGateway
from app.runner.spec import task_pack_for
from app.scoring.judge_prompts import (
    DOC_GRADE_SYSTEM,
    GRADE_SYSTEM,
    RANK_SYSTEM,
    doc_grade_instruction,
    gold_grade_instruction,
    ranking_instruction,
)
from app.scoring.judge_schemas import JudgeGradeOutput, JudgeRankingOutput


@dataclass(frozen=True)
class JudgeSummary:
    run_id: int
    judged_cells: int
    comparisons: int
    cost_usd: float
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ResultRecord:
    result_id: int
    document_id: int
    document_path: str
    task: str
    model_id: str
    parsed_output: dict[str, Any] | None
    gold: dict[str, Any] | None
    pack: str
    segmentation: dict[str, Any] | None


def anonymize_candidates(
    candidates: dict[str, Any], *, run_id: int, document_id: int
) -> tuple[dict[str, Any], dict[str, str], int]:
    """Return label->output, label->model, and a reproducible shuffle seed."""
    seed = (run_id << 32) ^ document_id
    model_ids = sorted(candidates)
    random.Random(seed).shuffle(model_ids)
    if len(model_ids) > len(ascii_uppercase):
        raise ValueError("head-to-head supports at most 26 candidates")
    labels = {ascii_uppercase[i]: model_id for i, model_id in enumerate(model_ids)}
    return ({label: candidates[model] for label, model in labels.items()}, labels, seed)


def de_anonymize_ranking(
    output: JudgeRankingOutput, labels: dict[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in output.ranking:
        label = row.candidate.removeprefix("Candidate ").strip()
        if label not in labels:
            raise ValueError(f"judge returned unknown candidate {row.candidate!r}")
        rows.append({"model_id": labels[label], **row.model_dump(exclude={"candidate"})})
    return rows


def _cfg_value(cfg: Any, name: str, default: Any) -> Any:
    return cfg.get(name, default) if isinstance(cfg, dict) else getattr(cfg, name, default)


def _load_records(session: Session, run_id: int) -> list[_ResultRecord]:
    gold = {
        (row.document_id, row.task): row.gold
        for row in session.exec(select(GroundTruth)).all()
    }
    run = session.get(BenchmarkRun, run_id)
    pack = run.pack if run else "OPD"
    rows = session.exec(
        select(RunResult, RunCell, DocumentSample)
        .join(RunCell, RunCell.id == RunResult.cell_id)  # type: ignore[arg-type]
        .join(DocumentSample, DocumentSample.id == RunCell.document_id)  # type: ignore[arg-type]
        .where(RunCell.run_id == run_id, RunResult.valid.is_(True))  # type: ignore[union-attr]
    ).all()
    return [
        _ResultRecord(
            result_id=result.id,
            document_id=cell.document_id,
            document_path=document.path,
            task=cell.task,
            model_id=cell.model_id,
            parsed_output=result.parsed_output,
            gold=gold.get((cell.document_id, cell.task)),
            pack=pack,
            segmentation=gold.get((cell.document_id, "segregation")),
        )
        for result, cell, document in rows
        if result.id is not None
    ]


def _judge_documents(record: _ResultRecord) -> list[DocumentInput]:
    page_ranges = None
    try:
        task = task_pack_for(record.pack).tasks[record.task]
    except (KeyError, NotImplementedError):
        task = None
    if task and task.document_types and record.segmentation:
        pages = [
            segment.get("pages")
            for segment in record.segmentation.get("segments", [])
            if segment.get("document_type") in task.document_types and segment.get("pages")
        ]
        page_ranges = ",".join(pages) or None
    return [
        DocumentInput(
            path=record.document_path,
            page_ranges=page_ranges,
            mime_type="application/pdf",
        )
    ]


def _upsert_grade(result_id: int, payload: dict[str, Any]) -> None:
    with Session(get_engine()) as session:
        score = session.exec(select(Score).where(Score.result_id == result_id)).first()
        if score is None:
            score = Score(result_id=result_id)
        previous = score.judge_score or {}
        grades = dict(previous.get("grades") or {})
        if previous.get("overall_score") is not None and previous.get("mode_used"):
            grades.setdefault(str(previous["mode_used"]), previous)
        grades[str(payload["mode_used"])] = payload
        score.judge_score = {**payload, "grades": grades}
        session.add(score)
        session.commit()


def _upsert_comparison(
    *, run_id: int, record: _ResultRecord, judge_model: str, payload: dict[str, Any], cost: float
) -> None:
    from app.models.judge import JudgeComparison

    with Session(get_engine()) as session:
        existing = session.exec(
            select(JudgeComparison).where(
                JudgeComparison.run_id == run_id,
                JudgeComparison.document_id == record.document_id,
                JudgeComparison.task_name == record.task,
                JudgeComparison.mode == "head_to_head",
                JudgeComparison.judge_model == judge_model,
            )
        ).first()
        row = existing or JudgeComparison(
            run_id=run_id,
            document_id=record.document_id,
            task_name=record.task,
            mode="head_to_head",
            judge_model=judge_model,
        )
        row.payload = payload
        row.rationale = str(payload.get("rationale", ""))
        row.cost_usd = cost
        session.add(row)
        session.commit()


async def judge_run(
    run_id: int,
    cfg: Any,
    *,
    concurrency: int = 4,
    gateway: ModelGateway | None = None,
) -> JudgeSummary:
    """Judge a completed run and persist all requested verdicts."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    model_id = _cfg_value(cfg, "model_id", "gemini-3.1-pro")
    modes = set(_cfg_value(cfg, "modes", ("gold_grade",)))
    unknown = modes - {"gold_grade", "doc_grade", "head_to_head"}
    if unknown:
        raise ValueError(f"unknown judge modes: {', '.join(sorted(unknown))}")

    with Session(get_engine()) as session:
        records = _load_records(session, run_id)
    judge = gateway or ModelGateway()
    semaphore = asyncio.Semaphore(concurrency)
    errors: list[str] = []
    costs: list[float] = []
    judged = 0
    grade_locks: dict[int, asyncio.Lock] = {}

    async def grade(record: _ResultRecord, requested_mode: str) -> None:
        nonlocal judged
        mode_used = requested_mode
        documents: list[DocumentInput] = []
        if requested_mode == "gold_grade" and record.gold is None:
            mode_used = "doc_grade"
        if mode_used == "gold_grade":
            system = GRADE_SYSTEM
            instruction = gold_grade_instruction(record.task, record.gold, record.parsed_output)
        else:
            system = DOC_GRADE_SYSTEM
            instruction = doc_grade_instruction(record.task, record.parsed_output)
            documents = _judge_documents(record)
        try:
            async with semaphore:
                result = await judge.structured(
                    model_id=model_id,
                    system=system,
                    instruction=instruction,
                    schema=JudgeGradeOutput,
                    documents=documents,
                )
            if not result.valid or not isinstance(result.parsed, JudgeGradeOutput):
                raise RuntimeError(str(result.error or "judge returned no valid grade"))
            cost = float(result.cost.total_usd)
            payload = {
                "mode": requested_mode,
                "mode_used": mode_used,
                "model": model_id,
                **result.parsed.model_dump(),
                "cost_usd": cost,
                "judged_at": datetime.now(UTC).isoformat(),
            }
            async with grade_locks.setdefault(record.result_id, asyncio.Lock()):
                await asyncio.to_thread(_upsert_grade, record.result_id, payload)
            costs.append(cost)
            judged += 1
        except Exception as exc:  # one failed judge cell must not abort the batch
            errors.append(f"{record.document_id}:{record.task}:{record.model_id}: {exc}")

    grade_jobs = []
    for record in records:
        if "gold_grade" in modes:
            grade_jobs.append(grade(record, "gold_grade"))
        if "doc_grade" in modes:
            grade_jobs.append(grade(record, "doc_grade"))
    await asyncio.gather(*grade_jobs)

    comparisons = 0
    if "head_to_head" in modes:
        grouped: dict[tuple[int, str], list[_ResultRecord]] = {}
        for record in records:
            grouped.setdefault((record.document_id, record.task), []).append(record)

        async def compare(group: list[_ResultRecord]) -> None:
            nonlocal comparisons
            first = group[0]
            candidates = {row.model_id: row.parsed_output for row in group}
            anonymous, labels, seed = anonymize_candidates(
                candidates, run_id=run_id, document_id=first.document_id
            )
            documents = (
                []
                if first.gold is not None
                else _judge_documents(first)
            )
            try:
                async with semaphore:
                    result = await judge.structured(
                        model_id=model_id,
                        system=RANK_SYSTEM,
                        instruction=ranking_instruction(
                            first.task, anonymous, first.gold
                        ),
                        schema=JudgeRankingOutput,
                        documents=documents,
                    )
                if not result.valid or not isinstance(result.parsed, JudgeRankingOutput):
                    raise RuntimeError(str(result.error or "judge returned no valid ranking"))
                cost = float(result.cost.total_usd)
                payload = {
                    "ranking": de_anonymize_ranking(result.parsed, labels),
                    "rationale": result.parsed.rationale,
                    "confidence": result.parsed.confidence,
                    "shuffle_seed": seed,
                    "judge_is_candidate": model_id in candidates,
                }
                await asyncio.to_thread(
                    _upsert_comparison,
                    run_id=run_id,
                    record=first,
                    judge_model=model_id,
                    payload=payload,
                    cost=cost,
                )
                costs.append(cost)
                comparisons += 1
            except Exception as exc:
                errors.append(f"{first.document_id}:{first.task}:head_to_head: {exc}")

        await asyncio.gather(*(compare(group) for group in grouped.values()))

    return JudgeSummary(
        run_id=run_id,
        judged_cells=judged,
        comparisons=comparisons,
        cost_usd=round(sum(costs), 8),
        errors=tuple(errors),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge a completed Colosseum run")
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--modes", default="gold_grade")
    parser.add_argument("--model", default="gemini-3.1-pro")
    args = parser.parse_args(argv)
    summary = asyncio.run(
        judge_run(
            args.run,
            {"model_id": args.model, "modes": args.modes.split(",")},
        )
    )
    print(summary)
    return int(bool(summary.errors))


if __name__ == "__main__":
    raise SystemExit(main())

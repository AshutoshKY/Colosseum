"""Dependency-aware parallel benchmark execution."""

from __future__ import annotations

import asyncio
import inspect
import json
import random
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.db import get_engine, session_scope
from app.models import BenchmarkRun, DocumentSample, RunCell, RunResult, RunStatus
from app.prompts.store import resolve_prompt
from app.providers.capabilities import Access
from app.providers.gateway import GatewayResult, ModelGateway
from app.providers.registry import get_capability
from app.runner.persistence import persist_cell_result
from app.runner.spec import RunSpec, runtime_config, task_pack_for
from app.runner.upstream import MissingUpstreamData, UpstreamResolver
from app.scoring.report import score_run
from app.tasks.base import Task, TaskPack

logger = get_logger(__name__)

# Self-deployed models (single-GPU vLLM boxes) can be far slower than managed/serverless
# endpoints, especially cold-start or under contention; a short task-default timeout causes
# spurious TimeoutErrors even when the endpoint is healthy. Floor, not a cap — an explicit
# task/run override above this value still wins.
SELF_DEPLOY_MIN_TIMEOUT_S = 1800.0

OPD_DEPENDS: dict[str, tuple[str, ...]] = {
    "segregation": (),
    "policy_extraction": (),
    "claim_form": ("segregation",),
    "identity_document": ("segregation",),
    "prescription": ("segregation",),
    "cheque_bank": ("segregation",),
    "itemized_bills": ("segregation",),
    "consolidated_bills": ("segregation",),
    "merge_bills": ("itemized_bills",),
    "items_categorisation": ("merge_bills",),
    "nme_analysis": ("merge_bills", "items_categorisation"),
    "extract_icd_codes": ("prescription", "merge_bills"),
    "patient_summary": (
        "claim_form",
        "prescription",
        "merge_bills",
        "cheque_bank",
        "identity_document",
    ),
    "benefit_plan": (
        "merge_bills",
        "items_categorisation",
        "policy_extraction",
    ),
    "audit": (
        "segregation",
        "nme_analysis",
        "patient_summary",
        "benefit_plan",
        "extract_icd_codes",
    ),
}
OPD_GOLD_KEYS: dict[str, tuple[str, ...]] = {
    "claim_form": ("segregation",),
    "identity_document": ("segregation",),
    "prescription": ("segregation",),
    "cheque_bank": ("segregation",),
    "itemized_bills": ("segregation",),
    "consolidated_bills": ("segregation",),
    "merge_bills": ("itemized_bills",),
    "items_categorisation": ("upstream_bills",),
    "nme_analysis": ("upstream_bills", "items_categorisation"),
    "extract_icd_codes": ("prescription", "upstream_bills"),
    "patient_summary": (
        "claim_form",
        "prescription",
        "upstream_bills",
        "cheque_bank",
        "identity_document",
    ),
    "benefit_plan": ("upstream_bills", "upstream_benefits", "policy_extraction"),
    "audit": (
        "segregation",
        "nme_analysis",
        "patient_summary",
        "benefit_plan",
        "extract_icd_codes",
    ),
}

OPTIONAL_OPD_TASKS: set[str] = {
    "cheque_bank",
    "identity_document",
    "claim_form",
    "discharge_summary",
    "consolidated_bills",
}


class EventSink(Protocol):
    def emit(self, event: dict[str, Any]) -> Awaitable[None] | None: ...


class NullEventSink:
    def emit(self, event: dict[str, Any]) -> None:
        del event


class _UpstreamCellFailed(RuntimeError):
    pass


def _final_run_status(session: Session, run_id: int) -> RunStatus:
    """Return the truthful terminal status for a non-cancelled run.

    A run is not completed merely because its worker finished.  Any failed cell, or a run
    where every cell was skipped (so no model result exists), is a failed run.
    """
    counts = _counts(session, run_id)
    if counts["failed"] or (counts["total"] and counts["skipped"] == counts["total"]):
        return RunStatus.failed
    return RunStatus.completed


def execution_pack(spec: RunSpec) -> TaskPack:
    pack = task_pack_for(spec.pack, spec.variant)
    if pack.name != "OPD" or any(task.depends_on for task in pack.tasks.values()):
        return pack
    tasks = {
        name: replace(
            task,
            depends_on=OPD_DEPENDS.get(name, ()),
            gold_feed_keys=OPD_GOLD_KEYS.get(name, task.gold_feed_keys),
        )
        for name, task in pack.tasks.items()
    }
    return TaskPack(pack.name, tasks, pack.order)


async def _emit(events: EventSink, event: dict[str, Any]) -> None:
    emitted = events.emit(event)
    if inspect.isawaitable(emitted):
        await emitted


def _cell_event(
    run_id: int,
    document: DocumentSample,
    cell: RunCell,
    *,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "cell",
        "run_id": run_id,
        "document_id": document.id,
        "document": Path(document.path).stem,
        "model_id": cell.model_id,
        "task": cell.task,
        "status": cell.status.value if isinstance(cell.status, RunStatus) else str(cell.status),
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "error": error,
        "skip_reason": cell.skip_reason,
    }


def _page_ranges(task: Task, resolver: UpstreamResolver) -> str | None:
    if not task.document_types:
        return None
    try:
        segmentation = resolver.get("segregation")
    except MissingUpstreamData:
        return None
    if not isinstance(segmentation, dict):
        return None
    segments = segmentation.get("segments", [])
    if not segments:
        return None
    pages = []
    for segment in segments:
        dtype = segment.get("document_type") or segment.get("segment_type")
        prange = segment.get("pages") or segment.get("page_range")
        if dtype in task.document_types and prange:
            pages.append(str(prange))
    if pages:
        return ",".join(pages)
    # If segregation ran and produced segments, but none match this document type,
    # return "__NONE__" so we know not to run on the entire document.
    return "__NONE__"


def _opd_instruction(task: Task, resolver: UpstreamResolver) -> str:
    from app.tasks.opd import (
        apply_categories,
        merge_bills,
        prepare_categorisation_input,
        prepare_nme_input,
    )

    def optional(name: str, default: Any = None) -> Any:
        try:
            return resolver.get(name)
        except MissingUpstreamData:
            return default

    upstream_bills = optional("merge_bills")
    itemized = optional("itemized_bills")
    consolidated = optional("consolidated_bills")
    if upstream_bills is not None:
        itemized, consolidated = upstream_bills, None
    benefits = optional("benefits", {})
    if isinstance(benefits, dict):
        benefits = benefits.get("benefits", [])
    merged = upstream_bills or merge_bills(itemized, consolidated)
    categorised = optional("items_categorisation")
    policy_context = optional("policy_extraction", {})
    if task.name == "items_categorisation":
        return task.render_instruction(
            bills_json=json.dumps(prepare_categorisation_input(merged))
        )
    if task.name == "nme_analysis":
        source = apply_categories(merged, categorised) if categorised else merged
        return task.render_instruction(bills_json=json.dumps(prepare_nme_input(source)))
    if task.name == "policy_extraction":
        return task.render_instruction(policy_context=json.dumps(policy_context))
    if task.name == "benefit_plan":
        source = apply_categories(merged, categorised) if categorised else merged
        context = {
            "bills": source.get("bills", []),
            "benefits": benefits,
            "policy_context": policy_context,
            "clinical_context": optional("prescription", {}),
        }
        return task.render_instruction(benefit_context=json.dumps(context))
    if task.name == "extract_icd_codes":
        rx = optional("prescription", {})
        clinical_details = rx.get("claims_digitization_details", rx) if isinstance(rx, dict) else {}
        bill_items = []
        for entry in (merged or {}).get("bills", []) or []:
            bid = (entry.get("bill") or {}).get("bill_id") or (entry.get("bill") or {}).get("invoice_number") or entry.get("bill_id")
            for it in entry.get("items", []) or []:
                iname = it.get("item_name") or it.get("description")
                if bid and iname:
                    bill_items.append({"bill_id": str(bid), "item_name": str(iname)})
        icd_payload = {
            "diagnosis": clinical_details.get("diagnosis"),
            "presenting_complaint": clinical_details.get("presenting_complaint"),
            "temperature_f": clinical_details.get("temperature_f"),
            "patient_age": clinical_details.get("patient_age"),
            "prescribed_items": clinical_details.get("prescribed_items", []),
            "bill_items": bill_items,
        }
        return task.render_instruction(context_json=json.dumps(icd_payload))
    context = {dep: optional(dep) for dep in task.depends_on}
    return task.render_instruction(context_json=json.dumps(context), **context)


def _opd_audit_system(template: str, resolver: UpstreamResolver) -> str:
    from app.tasks.opd import calculated_total, merge_bills

    try:
        merged = resolver.get("merge_bills")
    except MissingUpstreamData:
        try:
            merged = resolver.get("nme_analysis")
        except MissingUpstreamData:
            merged = merge_bills(
                resolver.get("itemized_bills"), resolver.get("consolidated_bills")
            )
    try:
        audit_gold = resolver.get("audit")
    except MissingUpstreamData:
        audit_gold = {}
    replacements = {
        "{{CLAIMED_AMOUNT}}": str(audit_gold.get("original_claimed_amount", 0)),
        "{{CALCULATED_TOTAL}}": str(calculated_total(merged)),
        "{{JSON_OUTPUT}}": json.dumps(merged),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template



def _failure(
    session: Session,
    cell: RunCell,
    *,
    system: str | None,
    instruction: str | None,
    prompt_version: str | None = None,
    error: str,
) -> RunResult:
    cell.status = RunStatus.failed
    session.add(cell)
    session.flush()
    row = RunResult(
        cell_id=cell.id,
        prompt_system=system,
        prompt_instruction=instruction,
        prompt_version=prompt_version,
        valid=False,
        error={"message": error},
    )
    session.add(row)
    session.flush()
    return row


def _deterministic(
    session: Session,
    cell: RunCell,
    task: Task,
    upstream: dict[str, Any],
) -> dict[str, Any]:
    output = task.run_transform(upstream)
    cell.status = RunStatus.succeeded
    session.add(cell)
    session.flush()
    session.add(
        RunResult(
            cell_id=cell.id,
            parsed_output=output,
            valid=True,
            structured_method="deterministic",
            prompt_version="code",
        )
    )
    session.flush()
    return output


async def _gateway_call(
    gateway: ModelGateway,
    *,
    model_id: str,
    system: str,
    instruction: str,
    prompt_version: str | None = None,
    task: Task,
    documents: list[Any],
    config: dict[str, Any],
) -> GatewayResult:
    for attempt in range(4):
        try:
            timeout = config.get("timeout_s")
            call = gateway.structured(
                model_id=model_id,
                system=system,
                instruction=instruction,
                schema=task.schema,
                documents=documents,
                config=config,
                prompt_version=prompt_version,
            )
            if timeout:
                async with asyncio.timeout(timeout):
                    return await call
            return await call
        except Exception as exc:
            if attempt == 3 or "429" not in str(exc):
                raise
            await asyncio.sleep(min(8.0, 0.5 * (2**attempt)) + random.random() * 0.25)
    raise AssertionError("unreachable")


async def execute_run(
    run_id: int,
    spec: RunSpec,
    events: EventSink | None = None,
    *,
    gateway_factory: Callable[[], ModelGateway] = ModelGateway,
) -> None:
    events = events or NullEventSink()
    engine = get_engine()
    pack = execution_pack(spec)
    plan = pack.resolve_subset(spec.selected_tasks, spec.upstream_mode)

    with session_scope(engine) as session:
        missing_docs = spec.validate_documents(session)
        if missing_docs:
            raise ValueError(f"Unknown document ids: {missing_docs}")
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            raise ValueError(f"Unknown run id: {run_id}")
        run.status = RunStatus.running
        session.add(run)
        existing = session.exec(select(RunCell).where(RunCell.run_id == run_id)).all()
        if not existing:
            for document_id in spec.document_ids:
                for model_id in spec.model_ids:
                    for task_name in spec.selected_tasks:
                        session.add(
                            RunCell(
                                run_id=run_id,
                                task=task_name,
                                document_id=document_id,
                                model_id=model_id,
                                config=runtime_config(spec, task_name, pack.tasks[task_name]),
                            )
                        )

    global_limit = asyncio.Semaphore(spec.concurrency.global_)
    provider_limits = {
        provider: asyncio.Semaphore(limit)
        for provider, limit in spec.concurrency.per_provider.items()
    }
    # Self-deployed endpoints (a single vLLM box) serialize badly: a call that runs in ~12s
    # solo balloons to ~44s under 2-way concurrency and times out under the shared provider
    # pool (openai_compatible defaults to 8). Cap each self-deployed *model* to one in-flight
    # request so calls queue cleanly instead of degrading into timeouts.
    self_deploy_limits: dict[str, asyncio.Semaphore] = {}
    gateway = gateway_factory()

    async def run_chain(document_id: int, model_id: str) -> None:
        live_outputs: dict[str, Any] = {}
        live_errors: dict[str, str] = {}
        with session_scope(engine) as session:
            document = session.get(DocumentSample, document_id)
            if document is None:
                return
            gold = UpstreamResolver.load_gold(session, document_id)
            cell_rows = session.exec(
                select(RunCell).where(
                    RunCell.run_id == run_id,
                    RunCell.document_id == document_id,
                    RunCell.model_id == model_id,
                )
            ).all()
            cells = {cell.task: cell.id for cell in cell_rows}
            result_rows = session.exec(
                select(RunResult).where(
                    RunResult.cell_id.in_([cell.id for cell in cell_rows if cell.id is not None])  # type: ignore[union-attr]
                )
            ).all()
            results_by_cell = {result.cell_id: result for result in result_rows}
            # A process restart loses in-memory upstream outputs. Restore successful
            # outputs from durable results so only unfinished cells are run again.
            for cell in cell_rows:
                status = cell.status.value if isinstance(cell.status, RunStatus) else str(cell.status)
                result = results_by_cell.get(cell.id)
                if status == RunStatus.succeeded.value and result and result.parsed_output is not None:
                    live_outputs[cell.task] = result.parsed_output
                elif status in {RunStatus.failed.value, RunStatus.skipped.value}:
                    live_errors[cell.task] = cell.skip_reason or f"previous_{status}:{cell.task}"
            document_data = document.model_dump()

        for layer in plan.layers:

            async def run_cell(task_name: str) -> None:
                task = pack.tasks[task_name]
                with session_scope(engine) as session:
                    document = DocumentSample.model_validate(document_data)
                    resolver = UpstreamResolver(session, document, gold, live_outputs)
                    cell_id = cells.get(task_name)
                    if cell_id is None:
                        cell = RunCell(
                            run_id=run_id,
                            task=task_name,
                            document_id=document_id,
                            model_id=model_id,
                            config=runtime_config(spec, task_name, task),
                        )
                        session.add(cell)
                        session.flush()
                        cells[task_name] = cell.id
                    else:
                        cell = session.get(RunCell, cell_id)
                    assert cell is not None
                    status = cell.status.value if isinstance(cell.status, RunStatus) else str(cell.status)
                    if status in {RunStatus.succeeded.value, RunStatus.failed.value, RunStatus.skipped.value}:
                        return
                    cell.status = RunStatus.running
                    session.add(cell)
                    session.flush()
                    running_event = _cell_event(run_id, document, cell)
                await _emit(events, running_event)

                system: str | None = None
                instruction: str | None = None
                try:
                    with session_scope(engine) as session:
                        document = DocumentSample.model_validate(document_data)
                        resolver = UpstreamResolver(session, document, gold, live_outputs)
                        failed_dependency = next(
                            (dep for dep in task.depends_on if dep in live_errors and dep not in OPTIONAL_OPD_TASKS), None
                        )
                        if failed_dependency:
                            raise _UpstreamCellFailed(live_errors[failed_dependency])
                        upstream = {}
                        for dep in task.depends_on:
                            try:
                                upstream[dep] = resolver.get(dep)
                            except MissingUpstreamData:
                                if dep in OPTIONAL_OPD_TASKS:
                                    upstream[dep] = {}
                                else:
                                    raise
                        cell = session.get(RunCell, cells[task_name])
                        assert cell is not None
                        if task.deterministic:
                            output = _deterministic(session, cell, task, upstream)
                            live_outputs[task_name] = output
                            event = _cell_event(run_id, document, cell, latency_ms=0, cost_usd=0.0)
                            await _emit(events, event)
                            return
                        else:
                            ranges = _page_ranges(task, resolver)
                            if ranges == "__NONE__":
                                empty_output: dict[str, Any] | None = None
                                if task_name == "cheque_bank":
                                    empty_output = {"bank_details": None}
                                elif task_name == "identity_document":
                                    empty_output = {"aadhaar": None, "pan": None}
                                elif task_name == "claim_form":
                                    empty_output = {"part_a": None, "part_b": None}
                                elif task_name in {"itemized_bills", "consolidated_bills"}:
                                    empty_output = {"bills": []}

                                if empty_output is not None:
                                    cell.status = RunStatus.succeeded
                                    session.add(cell)
                                    session.flush()
                                    session.add(
                                        RunResult(
                                            cell_id=cell.id,
                                            parsed_output=empty_output,
                                            valid=True,
                                            structured_method="no_document_pages",
                                            prompt_version="skipped_no_pages",
                                        )
                                    )
                                    session.flush()
                                    live_outputs[task_name] = empty_output
                                    event = _cell_event(run_id, document, cell, latency_ms=0, cost_usd=0.0)
                                    await _emit(events, event)
                                    return

                            prompt = resolve_prompt(
                                session,
                                spec.pack,
                                task,
                                spec.prompt_overrides.get(task_name),
                            )
                            system = prompt.system_prompt
                            instruction = prompt.instruction_template
                            rendered_task = replace(task, instruction=instruction)
                            if spec.pack == "OPD" and task.is_text_task:
                                instruction = _opd_instruction(rendered_task, resolver)
                            elif task.is_text_task:
                                instruction = rendered_task.render_instruction(**upstream)
                            elif spec.pack == "IPD" and upstream:
                                instruction = (
                                    f"{instruction}\n\nUPSTREAM CONTEXT:\n"
                                    f"{json.dumps(upstream, default=str)}"
                                )
                            if spec.pack == "OPD" and task_name == "audit":
                                system = _opd_audit_system(system, resolver)
                            documents = (
                                rendered_task.build_input(
                                    document.path,
                                    page_ranges=ranges,
                                ).documents
                                if rendered_task.requires_documents
                                else []
                            )
                            config = runtime_config(spec, task_name, task)
                    effective_model_id = str(config.get("model_id") or model_id)
                    effective_capability = get_capability(effective_model_id)
                    is_self_deploy = effective_capability.access == Access.self_deploy
                    if is_self_deploy:
                        config["timeout_s"] = max(
                            config.get("timeout_s") or 0, SELF_DEPLOY_MIN_TIMEOUT_S
                        )
                    provider = effective_capability.provider.value
                    provider_limit = provider_limits.get(provider)
                    if provider_limit is None:
                        provider_limit = provider_limits.setdefault(
                            provider, asyncio.Semaphore(min(spec.concurrency.global_, 4))
                        )
                    # A self-deployed box can't parallelize; serialize per model so concurrent
                    # cells queue instead of all degrading past the timeout.
                    endpoint_limit: AbstractAsyncContextManager[Any] = (
                        self_deploy_limits.setdefault(effective_model_id, asyncio.Semaphore(1))
                        if is_self_deploy
                        else nullcontext()
                    )
                    async with global_limit, provider_limit, endpoint_limit:
                        result = await _gateway_call(
                            gateway,
                            model_id=effective_model_id,
                            system=system,
                            instruction=instruction,
                            prompt_version=prompt.source,
                            task=task,
                            documents=documents,
                            config=config,
                        )
                    with session_scope(engine) as session:
                        document = DocumentSample.model_validate(document_data)
                        cell = session.get(RunCell, cells[task_name])
                        assert cell is not None
                        persist_cell_result(session, cell=cell, result=result)
                        if result.skipped:
                            logger.warning(
                                "run %s cell %s (%s/%s) skipped; no model call made: %s",
                                run_id,
                                cell.id,
                                task_name,
                                effective_model_id,
                                result.skip_reason,
                            )
                        elif result.error:
                            logger.error(
                                "run %s cell %s (%s/%s) model call failed: %s",
                                run_id,
                                cell.id,
                                task_name,
                                effective_model_id,
                                result.error.get("message") or result.error,
                            )
                        if result.parsed is not None:
                            live_outputs[task_name] = result.parsed.model_dump(mode="json")
                        else:
                            live_errors[task_name] = (result.error or {}).get(
                                "message"
                            ) or f"missing_upstream:{task_name}:upstream task produced no output"
                        event = _cell_event(
                            run_id,
                            document,
                            cell,
                            latency_ms=result.latency_ms,
                            cost_usd=float(result.cost.total_usd),
                            error=(result.error or {}).get("message") if result.error else None,
                        )
                except MissingUpstreamData as exc:
                    error = f"missing_upstream:{exc.task}:{exc}"
                    live_errors[task_name] = error
                    logger.error("run %s task %s failed: %s", run_id, task_name, error)
                    with session_scope(engine) as session:
                        document = DocumentSample.model_validate(document_data)
                        cell = session.get(RunCell, cells[task_name])
                        assert cell is not None
                        _failure(session, cell, system=system, instruction=instruction, error=error)
                        event = _cell_event(run_id, document, cell, error=error)
                except _UpstreamCellFailed as exc:
                    error = str(exc)
                    live_errors[task_name] = error
                    logger.error("run %s task %s skipped after upstream failure: %s", run_id, task_name, error)
                    with session_scope(engine) as session:
                        document = DocumentSample.model_validate(document_data)
                        cell = session.get(RunCell, cells[task_name])
                        assert cell is not None
                        _failure(session, cell, system=system, instruction=instruction, error=error)
                        event = _cell_event(run_id, document, cell, error=error)
                except Exception as exc:  # noqa: BLE001 -- isolate failures to this chain/cell
                    error = str(exc) or exc.__class__.__name__
                    live_errors[task_name] = error
                    logger.exception("run %s task %s failed", run_id, task_name)
                    with session_scope(engine) as session:
                        document = DocumentSample.model_validate(document_data)
                        cell = session.get(RunCell, cells[task_name])
                        assert cell is not None
                        _failure(session, cell, system=system, instruction=instruction, error=error)
                        event = _cell_event(run_id, document, cell, error=error)
                await _emit(events, event)

            await asyncio.gather(*(run_cell(task_name) for task_name in layer))

    chains = [run_chain(doc, model) for doc in spec.document_ids for model in spec.model_ids]
    try:
        await asyncio.gather(*chains, return_exceptions=True)
        with session_scope(engine) as session:
            score_run(session, run_id)
            run = session.get(BenchmarkRun, run_id)
            assert run is not None
            run.status = _final_run_status(session, run_id)
            session.add(run)
            if run.status == RunStatus.failed:
                logger.error("run %s failed; counts=%s", run_id, _counts(session, run_id))
        if spec.judge.enabled:
            try:
                from app.scoring.judge import judge_run
            except ImportError:
                logger.warning("judge requested but app.scoring.judge is not installed")
            else:
                await judge_run(run_id, spec.judge)
    except asyncio.CancelledError:
        with session_scope(engine) as session:
            pending = session.exec(
                select(RunCell).where(
                    RunCell.run_id == run_id,
                    RunCell.status.in_([RunStatus.pending, RunStatus.running]),  # type: ignore[union-attr]
                )
            ).all()
            for cell in pending:
                cell.status = RunStatus.skipped
                cell.skip_reason = "cancelled"
                session.add(cell)
            run = session.get(BenchmarkRun, run_id)
            if run:
                run.status = RunStatus.cancelled
                session.add(run)

    with session_scope(engine) as session:
        counts = _counts(session, run_id)
        run = session.get(BenchmarkRun, run_id)
        status = run.status.value if run and isinstance(run.status, RunStatus) else str(run.status)
    await _emit(events, {"type": "run", "run_id": run_id, "status": status, "counts": counts})


def _counts(session: Session, run_id: int) -> dict[str, int]:
    cells = session.exec(select(RunCell).where(RunCell.run_id == run_id)).all()
    counts = {"total": len(cells), "succeeded": 0, "failed": 0, "skipped": 0, "pending": 0}
    for cell in cells:
        status = cell.status.value if isinstance(cell.status, RunStatus) else str(cell.status)
        if status == "running":
            status = "pending"
        if status in counts:
            counts[status] += 1
    return counts

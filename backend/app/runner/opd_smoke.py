"""Cost-controlled live OPD smoke + the full-matrix entrypoint.

``run_opd_smoke`` runs the OPD priority tasks on a small number of PDFs (default 2) with
**Gemini first**, then with **each additional model the operator passes in** (intended: the
Model-Garden models you verified callable on the project). It persists a full ``run_result``
row per cell (tokens incl. thinking/cache, cost, latency, parsed output), scores against any
ground truth, and prints a composite scoreboard.

Document tasks (segregation, consolidated_bills, audit) feed the PDF through the adapter.
Text tasks (items_categorisation, nme_analysis) feed the prior stage's parsed JSON. A
capability-gated cell (text-only model on a document task) is recorded ``skipped`` / "not
applicable", never failed.

The **full** 27-PDF x all-models matrix is gated behind ``--full`` so it is never automatic.

Usage:
    # cost-controlled smoke: 2 PDFs, Gemini 2.5 Flash only
    uv run python -m app.runner.opd_smoke --docs 2

    # add more (verified) models
    uv run python -m app.runner.opd_smoke --docs 2 \
        --model vertex_ai/gemini-2.5-flash --model vertex_ai/zai-org/glm-5-maas

    # FULL matrix (explicit opt-in, controls spend)
    uv run python -m app.runner.opd_smoke --full --models-from-enabled
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import create_all, get_engine, session_scope
from app.models import BenchmarkRun, GroundTruth, RunCell, RunResult
from app.providers.gateway import GatewayResult, ModelGateway
from app.providers.registry import list_models
from app.runner.persistence import persist_cell_result, register_document
from app.scoring import build_scoreboard, score_against_gold
from app.scoring.scoreboard import ScoreboardRow
from app.tasks.opd import (
    OPD_TASKS,
    build_text_inputs,
    calculated_total,
    merge_bills,
)
from app.tasks.prompts.opd_healthpay import build_audit_prompt

logger = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/runner/opd_smoke.py -> Colosseum
TEST_DOCS = REPO_ROOT / "test-docs"

# A representative OPD policy context for the text tasks (the production payload supplies this).
_SAMPLE_POLICY_CONTEXT = {
    "policy_rules": [
        "Health check-up, vaccines and health supplements are not covered.",
        "Correction of eyesight, spectacles, contact lenses and hearing aids are not covered.",
        "Maximum consultation fee: 1000.",
    ],
    "nme_items": ["Registration Charges", "Documentation Charges", "Service Charges"],
}


def _pick_docs(n: int) -> list[Path]:
    pdfs = sorted(TEST_DOCS.glob("*.pdf"))
    return pdfs[:n]


def _docs_with_gold(engine) -> list[Path]:
    """Documents that have ground-truth rows, resolved back to test-docs paths."""
    from app.models import DocumentSample

    with session_scope(engine) as session:
        rows = session.exec(
            select(DocumentSample.path)
            .where(DocumentSample.id.in_(select(GroundTruth.document_id).distinct()))  # type: ignore[union-attr]
        ).all()
    docs: list[Path] = []
    for p in rows:
        path = Path(p)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if path.is_file():
            docs.append(path.resolve())
    return sorted(set(docs))


def _categorised_from_upstream(upstream: dict) -> dict:
    """Derive an items_categorisation-shaped payload from gold upstream bills."""
    groups = []
    for entry in upstream.get("bills", []) or []:
        bill_id = (entry.get("bill") or {}).get("bill_id")
        cat_items = [
            {"s.no.": it.get("s.no."), "category": it.get("category")}
            for it in entry.get("items", []) or []
            if it.get("category") and it.get("s.no.") is not None
        ]
        if bill_id and cat_items:
            groups.append({"bill_id": bill_id, "categorized_items": cat_items})
    return {"bill_item_categories": groups}


# Seconds to sleep between cells (set via --pause) to stay under Vertex per-minute quotas.
_PAUSE_SECONDS: float = 0.0


async def _run_cell(
    gateway: ModelGateway,
    *,
    session: Session,
    run: BenchmarkRun,
    model_id: str,
    task_name: str,
    doc_path: str,
    instruction: str | None = None,
    system: str | None = None,
) -> tuple[RunResult, GatewayResult]:
    if _PAUSE_SECONDS:
        await asyncio.sleep(_PAUSE_SECONDS)
    task = OPD_TASKS[task_name]
    doc = register_document(session, doc_path, claim_type="OPD")
    session.flush()
    documents = [] if task.is_text_task else task.build_input(doc_path).documents
    result = await gateway.structured(
        model_id=model_id,
        system=system if system is not None else task.system_prompt,
        instruction=instruction if instruction is not None else task.instruction,
        schema=task.schema,
        documents=documents,
    )
    cell = RunCell(
        run_id=run.id, task=task_name, document_id=doc.id, model_id=model_id, config={}
    )
    session.add(cell)
    session.flush()
    row = persist_cell_result(session, cell=cell, result=result)
    return row, result


def _gold_for(session: Session, document_id: int, task: str) -> dict | None:
    gt = session.exec(
        select(GroundTruth).where(
            GroundTruth.document_id == document_id, GroundTruth.task == task
        )
    ).first()
    return gt.gold if gt else None


async def run_opd_smoke(
    *,
    n_docs: int = 2,
    models: list[str] | None = None,
    db_url: str | None = None,
    full: bool = False,
    tasks: list[str] | None = None,
    gold_upstream: bool = False,
    docs_from_gold: bool = False,
) -> int:
    settings = get_settings()
    # Gemini first, then the operator-supplied (verified) models.
    gemini_default = settings.colosseum_default_gemini_model
    models = models or [gemini_default]
    if gemini_default not in models:
        models = [gemini_default, *models]

    selected = set(tasks) if tasks else set(OPD_TASKS)
    unknown = selected - set(OPD_TASKS)
    if unknown:
        print(f"Unknown task(s): {sorted(unknown)}; valid: {sorted(OPD_TASKS)}", file=sys.stderr)
        return 2

    engine = get_engine(db_url) if db_url else get_engine()
    if db_url:
        create_all(engine)

    if docs_from_gold:
        docs = _docs_with_gold(engine)
        if not full:
            docs = docs[:n_docs] if n_docs else docs
    else:
        docs = _pick_docs(n_docs if not full else 9999)
    if not docs:
        print(f"No PDFs found ({'gold-matched' if docs_from_gold else str(TEST_DOCS)})", file=sys.stderr)
        return 2

    gateway = ModelGateway()
    scoreboard_rows: list[ScoreboardRow] = []

    with session_scope(engine) as session:
        run = BenchmarkRun(name=f"opd-smoke:{'full' if full else f'{n_docs}docs'}", task_pack_version="opd-v1")
        session.add(run)
        session.flush()

        for doc_path in docs:
            dp = str(doc_path)
            doc = register_document(session, dp, claim_type="OPD")
            session.flush()
            # Golden upstream context (production merged categorised bills + policy + claimed
            # amount) so a dependent task consumes GOLD data instead of another model's output.
            gold_upstream_bills = _gold_for(session, doc.id, "upstream_bills") if gold_upstream else None
            gold_policy = _gold_for(session, doc.id, "policy_extraction") if gold_upstream else None
            gold_audit = _gold_for(session, doc.id, "audit") if gold_upstream else None
            gold_benefits = (
                (_gold_for(session, doc.id, "upstream_benefits") or {}).get("benefits")
                if gold_upstream else None
            )
            gold_claimed = (gold_audit or {}).get("original_claimed_amount", 0) if gold_upstream else 0
            policy_context = (
                {"policy_rules": gold_policy.get("policy_rules", []), "nme_items": gold_policy.get("nme_items", [])}
                if gold_policy else _SAMPLE_POLICY_CONTEXT
            )
            for model_id in models:
                # ===== PIPE: segregation -> itemized_bills -> consolidated_bills =====
                # (audit runs LAST, after the assembled JSON is available). One document flows
                # end-to-end through the pack for this model.
                parsed_by_task: dict[str, dict] = {}
                for task_name in ("segregation", "itemized_bills", "consolidated_bills"):
                    if task_name not in selected:
                        continue
                    row, result = await _run_cell(
                        gateway, session=session, run=run, model_id=model_id,
                        task_name=task_name, doc_path=dp,
                    )
                    if result.parsed is not None:
                        parsed_by_task[task_name] = result.parsed.model_dump(mode="json")
                    scoreboard_rows.append(
                        _to_scoreboard_row(session, task_name, model_id, row, result)
                    )

                itemized = parsed_by_task.get("itemized_bills")
                consolidated = parsed_by_task.get("consolidated_bills")
                if gold_upstream and gold_upstream_bills:
                    merged = gold_upstream_bills
                else:
                    merged = merge_bills(itemized, consolidated)

                # ===== TEXT PIPE (explicit upstream->downstream wiring) =====
                # policy_extraction & items_categorisation run on the merged bills; nme &
                # benefit_plan run on the categorised bills produced by items_categorisation.
                # In --gold-upstream mode the upstream data comes from ground truth.
                categorised = (
                    _categorised_from_upstream(gold_upstream_bills)
                    if gold_upstream and gold_upstream_bills else None
                )
                text_itemized = gold_upstream_bills if gold_upstream and gold_upstream_bills else itemized
                text_consolidated = None if gold_upstream and gold_upstream_bills else consolidated

                # policy_extraction + items_categorisation
                for task_name in ("policy_extraction", "items_categorisation"):
                    if task_name not in selected:
                        continue
                    inputs = build_text_inputs(
                        itemized=text_itemized, consolidated=text_consolidated,
                        policy_context=policy_context,
                    )
                    row, result = await _run_cell(
                        gateway, session=session, run=run, model_id=model_id,
                        task_name=task_name, doc_path=dp, instruction=inputs[task_name],
                    )
                    if (
                        task_name == "items_categorisation"
                        and result.parsed is not None
                        and categorised is None
                    ):
                        categorised = result.parsed.model_dump(mode="json")
                    scoreboard_rows.append(
                        _to_scoreboard_row(session, task_name, model_id, row, result)
                    )

                # nme_analysis + benefit_plan consume the categorised bills (<- items_categorisation)
                for task_name in ("nme_analysis", "benefit_plan"):
                    if task_name not in selected:
                        continue
                    inputs = build_text_inputs(
                        itemized=text_itemized, consolidated=text_consolidated,
                        categorised=categorised, policy_context=policy_context,
                        benefits=gold_benefits, claimed_amount=gold_claimed,
                    )
                    row, result = await _run_cell(
                        gateway, session=session, run=run, model_id=model_id,
                        task_name=task_name, doc_path=dp, instruction=inputs[task_name],
                    )
                    scoreboard_rows.append(
                        _to_scoreboard_row(session, task_name, model_id, row, result)
                    )

                # ===== audit (<- assembled JSON of merged bills + calculated total) =====
                if "audit" in selected:
                    audit_system = build_audit_prompt(
                        claimed_amount=gold_claimed,
                        calculated_total=calculated_total(merged),
                        extracted_json=json.dumps(merged),
                    )
                    row, result = await _run_cell(
                        gateway, session=session, run=run, model_id=model_id,
                        task_name="audit", doc_path=dp, system=audit_system,
                    )
                    scoreboard_rows.append(
                        _to_scoreboard_row(session, "audit", model_id, row, result)
                    )

        build_scoreboard(scoreboard_rows)
        _print_scoreboard(scoreboard_rows, models=models, docs=docs)
        run.status = run.status  # left pending->ok; status transitions are Phase-4 concern
        session.add(run)

    from app.observability import flush

    flush()
    return 0


def _to_scoreboard_row(
    session: Session, task: str, model_id: str, row: RunResult, result: GatewayResult
) -> ScoreboardRow:
    accuracy: float | None = None
    if result.parsed is not None and not result.skipped:
        gold = _gold_for(session, _cell_doc_id(session, row.cell_id), task)
        if gold is not None:
            accuracy = score_against_gold(result.parsed.model_dump(mode="json"), gold).accuracy
    return ScoreboardRow(
        task=task,
        model_id=model_id,
        valid=result.valid,
        accuracy=accuracy,
        total_cost_usd=float(result.cost.total_usd),
        latency_ms=result.latency_ms,
        skipped=result.skipped,
        skip_reason=result.skip_reason,
    )


def _cell_doc_id(session: Session, cell_id: int | None) -> int:
    cell = session.get(RunCell, cell_id)
    return cell.document_id if cell else -1


def _print_scoreboard(rows: list[ScoreboardRow], *, models: list[str], docs: list[Path]) -> None:
    print("\n=== OPD SMOKE: models x docs ===")
    print(f"models: {models}")
    print(f"docs:   {[d.name for d in docs]}")
    print("\n--- run cells ---")
    for r in rows:
        if r.skipped:
            print(f"  [skip] {r.task:22} {r.model_id:42} not applicable: {r.skip_reason}")
        else:
            print(
                f"  {r.task:22} {r.model_id:42} valid={r.valid} "
                f"cost=${r.total_cost_usd:.6f} lat={r.latency_ms}ms "
                f"acc={r.accuracy if r.accuracy is not None else 'n/a'}"
            )
    print("\n--- composite scoreboard (per task, rank 1 = best) ---")
    for r in sorted([x for x in rows if not x.skipped], key=lambda x: (x.task, x.rank or 99)):
        print(
            f"  #{r.rank} {r.task:22} {r.model_id:42} composite={r.composite:.4f} "
            f"(valid={r.valid} cost=${r.total_cost_usd:.6f} lat={r.latency_ms}ms)"
        )
    print("================================\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cost-controlled live OPD smoke (+ full matrix opt-in).")
    parser.add_argument("--docs", type=int, default=2, help="number of PDFs from test-docs/ (smoke).")
    parser.add_argument("--model", dest="models", action="append", default=[], help="extra model id (repeatable).")
    parser.add_argument("--models-from-enabled", action="store_true", help="use every registry-enabled model.")
    parser.add_argument("--full", action="store_true", help="run the FULL 27-PDF matrix (explicit opt-in).")
    parser.add_argument("--db-url", dest="db_url", default=None, help="override DB URL (e.g. sqlite).")
    parser.add_argument(
        "--tasks", default=None,
        help="comma-separated subset of OPD tasks to run live (default: all).",
    )
    parser.add_argument(
        "--gold-upstream", action="store_true",
        help="feed dependent tasks (audit, categorisation, nme, benefit_plan) from golden "
             "ground-truth upstream data instead of the model's own upstream outputs.",
    )
    parser.add_argument(
        "--docs-from-gold", action="store_true",
        help="run on the documents that have ground truth (instead of the first N PDFs).",
    )
    parser.add_argument(
        "--pause", type=float, default=0.0,
        help="seconds to sleep between cells (rate-limit cushion for Vertex quotas).",
    )
    args = parser.parse_args(argv)
    global _PAUSE_SECONDS
    _PAUSE_SECONDS = max(args.pause, 0.0)

    models = list(args.models)
    if args.models_from_enabled:
        models = [c.model_id for c in list_models(enabled_only=True)]

    if args.full:
        print("WARNING: --full runs every task x model on ALL test-docs PDFs. This costs money.")
    return asyncio.run(
        run_opd_smoke(
            n_docs=args.docs, models=models or None, db_url=args.db_url, full=args.full,
            tasks=[t.strip() for t in args.tasks.split(",")] if args.tasks else None,
            gold_upstream=args.gold_upstream,
            docs_from_gold=args.docs_from_gold,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Persistence + registry smoke tests (offline, sqlite)."""

from __future__ import annotations

from decimal import Decimal

from app.db import create_all, get_engine, session_scope
from app.models import BenchmarkRun, RunCell, RunStatus
from app.providers.gateway import GatewayResult
from app.providers.pricing import EstimatedCost
from app.providers.registry import list_models
from app.providers.usage import NormalizedUsage
from app.runner.persistence import persist_cell_result, register_document
from app.tasks.schemas.bills import (
    BillHeader,
    ItemizedBillGroup,
    ItemizedBillItem,
    ItemizedBillsOutput,
)


def test_registry_matches_doc_gemini_enabled():
    enabled = {c.model_id for c in list_models(enabled_only=True)}
    assert "vertex_ai/gemini-2.5-flash" in enabled
    # stubs disabled
    assert "xai/grok-4" not in enabled
    assert "vertex_ai/deepseek-r1" not in enabled


def test_persist_full_run_result(synthetic_pdf):
    engine = get_engine("sqlite://")
    create_all(engine)

    parsed = ItemizedBillsOutput(
        bills=[
            ItemizedBillGroup(
                bill=BillHeader(invoice_number="INV-1", net_amount=300.0),
                items=[ItemizedBillItem(item_name="Paracetamol", final_amount=300.0)],
            )
        ]
    )
    usage = NormalizedUsage(
        input_tokens=5000, output_tokens=800, thinking_tokens=200, cached_tokens=100, total_tokens=6100
    )
    cost = EstimatedCost(
        input_usd=Decimal("0.0015"),
        output_usd=Decimal("0.002"),
        cache_usd=Decimal("0.000003"),
        thinking_usd=Decimal("0.0005"),
        total_usd=Decimal("0.004003"),
        pricing_version="colosseum-2026-06",
        pricing_ref="gemini-2.5-flash",
    )
    result = GatewayResult(
        model_id="vertex_ai/gemini-2.5-flash",
        parsed=parsed,
        valid=True,
        usage=usage,
        cost=cost,
        latency_ms=1234,
        retries=0,
        raw_response={"id": "x"},
        usage_raw={"prompt_token_count": 5000},
        structured_method="json_schema",
        endpoint="default",
    )

    with session_scope(engine) as session:
        doc = register_document(session, synthetic_pdf, claim_type="health_claim")
        # idempotent
        doc2 = register_document(session, synthetic_pdf)
        assert doc.id == doc2.id

        run = BenchmarkRun(name="t")
        session.add(run)
        session.flush()
        cell = RunCell(run_id=run.id, task="itemized_bills", document_id=doc.id, model_id=result.model_id)
        session.add(cell)
        session.flush()
        row = persist_cell_result(session, cell=cell, result=result)
        assert row.id is not None
        assert cell.status == RunStatus.succeeded
        assert row.total_tokens == 6100
        assert row.thinking_tokens == 200
        assert float(row.total_cost_usd) == 0.004003
        assert row.parsed_output["bills"][0]["items"][0]["item_name"] == "Paracetamol"


def test_persist_skipped_cell(synthetic_pdf):
    engine = get_engine("sqlite://")
    create_all(engine)
    result = GatewayResult(
        model_id="vertex_ai/deepseek-r1",
        parsed=None,
        valid=False,
        usage=NormalizedUsage(),
        cost=EstimatedCost(
            Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(0), "n/a", None
        ),
        latency_ms=0,
        skipped=True,
        skip_reason="text-only model",
    )
    with session_scope(engine) as session:
        doc = register_document(session, synthetic_pdf)
        run = BenchmarkRun(name="t")
        session.add(run)
        session.flush()
        cell = RunCell(run_id=run.id, task="itemized_bills", document_id=doc.id, model_id=result.model_id)
        session.add(cell)
        session.flush()
        persist_cell_result(session, cell=cell, result=result)
        assert cell.status == RunStatus.skipped
        assert cell.skip_reason == "text-only model"

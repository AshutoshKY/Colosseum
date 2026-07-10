import asyncio
from dataclasses import replace
from decimal import Decimal

import app.runner.engine as engine_module
import pytest
from app.models import BenchmarkRun, DocumentSample, RunCell, RunResult, RunStatus
from app.providers.gateway import GatewayResult
from app.providers.pricing import EstimatedCost
from app.providers.registry import get_capability, list_models
from app.providers.usage import NormalizedUsage
from app.runner.engine import _opd_instruction, execute_run
from app.runner.spec import ConcurrencySpec, RunSpec
from sqlmodel import Session, SQLModel, create_engine, select


def _cost() -> EstimatedCost:
    zero = Decimal("0")
    return EstimatedCost(zero, zero, zero, zero, zero, "test", None)


class FakeGateway:
    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.inflight = 0
        self.max_inflight = 0
        self.models: list[str] = []

    async def structured(self, **kwargs) -> GatewayResult:
        self.models.append(kwargs["model_id"])
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(self.delay)
            parsed = kwargs["schema"].model_validate({"segments": []})
            return GatewayResult(
                model_id=kwargs["model_id"],
                parsed=parsed,
                valid=True,
                usage=NormalizedUsage(),
                cost=_cost(),
                latency_ms=int(self.delay * 1000),
                prompt_system=kwargs["system"],
                prompt_instruction=kwargs["instruction"],
                document_count=len(kwargs["documents"]),
            )
        finally:
            self.inflight -= 1


class Events:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def emit(self, event: dict) -> None:
        self.items.append(event)


def _setup(tmp_path, count: int = 3):
    db = create_engine(
        f"sqlite:///{tmp_path / 'engine.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(db)
    with Session(db) as session:
        docs = [DocumentSample(path=f"claim-{i}.pdf", sha256=f"engine-{i}") for i in range(count)]
        session.add_all(docs)
        session.flush()
        run = BenchmarkRun(name="engine", pack="OPD")
        session.add(run)
        session.commit()
        return db, run.id, [doc.id for doc in docs]


def _model() -> str:
    return list_models(enabled_only=True)[0].model_id


def test_opd_text_prompt_override_is_the_template_actually_rendered() -> None:
    from app.tasks.opd import ITEMS_CATEGORISATION

    class Resolver:
        def get(self, name):
            if name == "merge_bills":
                return {"bills": []}
            raise engine_module.MissingUpstreamData(name, DocumentSample(path="x", sha256="x"))

    task = replace(ITEMS_CATEGORISATION, instruction="OVERRIDE::{bills_json}")
    assert _opd_instruction(task, Resolver()).startswith("OVERRIDE::")


@pytest.mark.asyncio
async def test_parallel_engine_persists_grid_and_respects_provider_limit(
    tmp_path, monkeypatch
) -> None:
    db, run_id, document_ids = _setup(tmp_path)
    monkeypatch.setattr(engine_module, "get_engine", lambda: db)
    model_id = _model()
    provider = get_capability(model_id).provider.value
    spec = RunSpec(
        name="parallel",
        pack="OPD",
        selected_tasks=["segregation"],
        document_ids=document_ids,
        model_ids=[model_id],
        upstream_mode="gold",
        concurrency=ConcurrencySpec(global_=4, per_provider={provider: 2}),
    )
    gateway = FakeGateway()
    events = Events()

    await execute_run(run_id, spec, events, gateway_factory=lambda: gateway)

    assert gateway.max_inflight == 2
    with Session(db) as session:
        cells = session.exec(select(RunCell)).all()
        results = session.exec(select(RunResult)).all()
        assert len(cells) == len(results) == 3
        assert {cell.status for cell in cells} == {RunStatus.succeeded}
        assert all(row.prompt_system and row.prompt_instruction for row in results)
        assert session.get(BenchmarkRun, run_id).status == RunStatus.completed
    assert events.items[-1]["type"] == "run"
    assert events.items[-1]["counts"]["succeeded"] == 3


@pytest.mark.asyncio
async def test_task_model_override_is_used_for_gateway_call(tmp_path, monkeypatch) -> None:
    db, run_id, document_ids = _setup(tmp_path, 1)
    monkeypatch.setattr(engine_module, "get_engine", lambda: db)
    models = [cap.model_id for cap in list_models(enabled_only=True)]
    spec = RunSpec(
        name="override",
        pack="OPD",
        selected_tasks=["segregation"],
        document_ids=document_ids,
        model_ids=[models[0]],
        runtime_overrides={"segregation": {"model_id": models[1]}},
    )
    gateway = FakeGateway(delay=0)
    await execute_run(run_id, spec, Events(), gateway_factory=lambda: gateway)
    assert gateway.models == [models[1]]


@pytest.mark.asyncio
async def test_missing_gold_fails_cell_without_gateway_call(tmp_path, monkeypatch) -> None:
    db, run_id, document_ids = _setup(tmp_path, 1)
    monkeypatch.setattr(engine_module, "get_engine", lambda: db)
    model_id = _model()
    spec = RunSpec(
        name="missing-gold",
        pack="OPD",
        selected_tasks=["audit"],
        document_ids=document_ids,
        model_ids=[model_id],
        upstream_mode="gold",
    )
    gateway = FakeGateway()
    await execute_run(run_id, spec, Events(), gateway_factory=lambda: gateway)
    assert gateway.max_inflight == 0
    with Session(db) as session:
        cell = session.exec(select(RunCell)).one()
        result = session.exec(select(RunResult)).one()
        assert cell.status == RunStatus.failed
        assert result.error["message"].startswith("missing_upstream:")


@pytest.mark.asyncio
async def test_cancel_marks_unfinished_cells_skipped(tmp_path, monkeypatch) -> None:
    db, run_id, document_ids = _setup(tmp_path, 4)
    monkeypatch.setattr(engine_module, "get_engine", lambda: db)
    model_id = _model()
    provider = get_capability(model_id).provider.value
    spec = RunSpec(
        name="cancel",
        pack="OPD",
        selected_tasks=["segregation"],
        document_ids=document_ids,
        model_ids=[model_id],
        upstream_mode="gold",
        concurrency=ConcurrencySpec(global_=1, per_provider={provider: 1}),
    )
    task = asyncio.create_task(
        execute_run(run_id, spec, Events(), gateway_factory=lambda: FakeGateway(delay=1))
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await task
    with Session(db) as session:
        cells = session.exec(select(RunCell)).all()
        assert all(cell.status == RunStatus.skipped for cell in cells)
        assert all(cell.skip_reason == "cancelled" for cell in cells)
        assert session.get(BenchmarkRun, run_id).status == RunStatus.cancelled

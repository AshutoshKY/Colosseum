from __future__ import annotations

import asyncio
import json
from io import BytesIO

import httpx
import pytest
from app.api.deps import get_run_manager
from app.api.main import app
from app.api.routers import documents
from app.db import create_all
from app.db import engine as db_engine
from app.models import (
    BenchmarkRun,
    GroundTruth,
    RunCell,
    RunResult,
    RunStatus,
    Score,
)
from app.runner.persistence import register_document
from app.runner.spec import RunSpec
from openapi_spec_validator import validate
from pypdf import PdfWriter
from sqlmodel import Session, select


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture()
def api_engine(tmp_path, monkeypatch):
    engine = db_engine.get_engine(f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr(db_engine, "_engine", engine)
    monkeypatch.setattr(documents, "UPLOAD_DIR", tmp_path / "uploads")
    create_all(engine)
    yield engine
    app.dependency_overrides.clear()


@pytest.fixture()
async def client(api_engine):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


async def test_health_openapi_catalog_and_packs(client):
    assert (await client.get("/api/health")).json() == {"status": "ok"}
    schema = (await client.get("/openapi.json")).json()
    validate(schema)
    assert "/api/runs/{run_id}/events" in schema["paths"]
    catalog = (await client.get("/api/catalog")).json()
    assert catalog["models"] and catalog["providers"]
    packs = (await client.get("/api/packs")).json()
    assert [pack["name"] for pack in packs] == ["OPD", "IPD"]
    audit = next(task for task in packs[0]["tasks"] if task["name"] == "audit")
    assert "segregation" in audit["depends_on"]
    assert "nme_analysis" in audit["gold_feed_keys"]
    assert "patient_summary" in audit["gold_feed_keys"]


async def test_upload_dedupe_gold_and_prompt_versions(client, api_engine):
    payload = _pdf()
    first = await client.post(
        "/api/documents", files=[("files", ("claim.pdf", payload, "application/pdf"))]
    )
    second = await client.post(
        "/api/documents", files=[("files", ("same.pdf", payload, "application/pdf"))]
    )
    assert first.status_code == 201
    assert second.json()[0]["id"] == first.json()[0]["id"]
    document_id = first.json()[0]["id"]

    bad = await client.post(
        "/api/documents", files=[("files", ("fake.pdf", b"not pdf", "application/pdf"))]
    )
    assert bad.status_code == 415

    saved = await client.put(
        f"/api/gold/{document_id}",
        json={"tasks": {"segregation": {"segments": []}}},
    )
    assert saved.json()["tasks"]["segregation"] == {"segments": []}
    listed = (await client.get("/api/documents")).json()
    assert listed[0]["has_gold"] is True
    assert listed[0]["gold_keys"] == ["segregation"]

    imported = await client.post(
        "/api/gold/import",
        files=[
            (
                "file",
                (
                    "gold.json",
                    json.dumps(
                        {
                            "document": first.json()[0]["sha256"],
                            "tasks": {"audit": {"status": "MATCH"}},
                        }
                    ),
                    "application/json",
                ),
            )
        ],
    )
    assert imported.status_code == 200
    assert imported.json()["inserted"] == 1

    one = await client.post(
        "/api/prompts/OPD/segregation/versions",
        json={"system_prompt": "one", "instruction_template": "first", "activate": True},
    )
    two = await client.post(
        "/api/prompts/OPD/segregation/versions",
        json={"system_prompt": "two", "instruction_template": "second", "activate": True},
    )
    assert one.json()["version"] == 1
    assert two.json()["version"] == 2
    history = (await client.get("/api/prompts/OPD/segregation/versions")).json()
    assert [row["active"] for row in history] == [True, False]
    active = (await client.get("/api/prompts?pack=OPD")).json()[0]
    assert active["active_version"] == 2
    assert active["differs_from_code"] is True


def _spec(document_id: int, **updates) -> RunSpec:
    values = {
        "name": "api-test",
        "pack": "OPD",
        "selected_tasks": ["segregation"],
        "document_ids": [document_id],
        "model_ids": ["vertex_ai/gemini-2.5-flash-lite"],
    }
    values.update(updates)
    return RunSpec.model_validate(values)


async def test_dry_run_missing_gold_and_fake_launch(client, api_engine, tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(_pdf())
    with Session(api_engine) as session:
        document = register_document(session, str(path), claim_type="OPD")
        session.commit()
        document_id = document.id
    assert document_id is not None

    dry = await client.post(
        "/api/runs/dry-run", json=_spec(document_id).model_dump(mode="json", by_alias=True)
    )
    assert dry.status_code == 200
    assert dry.json()["layers"] == [["segregation"]]
    assert dry.json()["cost_estimate"]["estimated"] is True

    missing = _spec(document_id, selected_tasks=["audit"])
    response = await client.post(
        "/api/runs/dry-run", json=missing.model_dump(mode="json", by_alias=True)
    )
    assert response.status_code == 422
    assert str(document_id) in response.json()["missing_gold"]

    class FakeManager:
        async def launch(self, spec):
            assert spec.name == "api-test"
            return 41

    app.dependency_overrides[get_run_manager] = lambda: FakeManager()
    launched = await client.post(
        "/api/runs", json=_spec(document_id).model_dump(mode="json", by_alias=True)
    )
    assert launched.status_code == 202
    assert launched.json() == {"run_id": 41, "status": "running"}


def _seed_run(engine, tmp_path) -> tuple[int, int]:
    path = tmp_path / "result.pdf"
    path.write_bytes(_pdf())
    spec: RunSpec | None = None
    with Session(engine) as session:
        document = register_document(session, str(path), claim_type="OPD")
        session.flush()
        spec = _spec(document.id)
        run = BenchmarkRun(
            name="finished",
            pack="OPD",
            task_pack_version="v2",
            status=RunStatus.completed,
            spec=spec.model_dump(mode="json", by_alias=True),
        )
        session.add(run)
        session.flush()
        cell = RunCell(
            run_id=run.id,
            document_id=document.id,
            task="segregation",
            model_id=spec.model_ids[0],
            status=RunStatus.succeeded,
        )
        session.add(cell)
        session.flush()
        result = RunResult(
            cell_id=cell.id,
            parsed_output={"segments": [{"document_type": "bill", "pages": "1"}]},
            raw_response={"segments": [{"document_type": "bill", "pages": "1"}]},
            prompt_system="system",
            prompt_instruction="instruction",
            valid=True,
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
            total_cost_usd=0.01,
            latency_ms=50,
        )
        session.add(result)
        session.flush()
        session.add(
            GroundTruth(
                document_id=document.id,
                task="segregation",
                gold={"segments": [{"document_type": "bill", "pages": "1"}]},
            )
        )
        session.add(
            Score(
                result_id=result.id,
                field_metrics={
                    "accuracy": 1.0,
                    "details": {"fields": {"segments": {"matched": 1, "total": 1}}},
                },
            )
        )
        session.commit()
        return run.id, document.id


async def test_rename_export_and_delete_run(client, api_engine, tmp_path):
    run_id, _ = _seed_run(api_engine, tmp_path)

    renamed = await client.patch(f"/api/runs/{run_id}", json={"name": "renamed run"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "renamed run"
    assert (await client.patch("/api/runs/9999", json={"name": "x"})).status_code == 404

    exported = await client.get(f"/api/runs/{run_id}/export?format=json")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    payload = exported.json()
    assert payload["run"]["name"] == "renamed run"
    assert payload["results"][0]["raw_response"] is not None

    csv_export = await client.get(f"/api/runs/{run_id}/export?format=csv")
    assert csv_export.status_code == 200
    header, row = csv_export.text.splitlines()[:2]
    assert header.startswith("document_id,document_name,model_id,task,status")
    assert "segregation" in row

    assert (await client.delete(f"/api/runs/{run_id}")).status_code == 204
    assert (await client.get(f"/api/runs/{run_id}")).status_code == 404
    with Session(api_engine) as session:
        assert session.exec(select(RunCell)).all() == []
        assert session.exec(select(RunResult)).all() == []
        assert session.exec(select(Score)).all() == []


async def test_run_results_comparisons_judge_and_sse(client, api_engine, tmp_path, monkeypatch):
    run_id, document_id = _seed_run(api_engine, tmp_path)
    detail = (await client.get(f"/api/runs/{run_id}")).json()
    assert detail["run"]["counts"]["succeeded"] == 1
    assert detail["cells"][0]["document_name"] == "result.pdf"

    hidden = (await client.get(f"/api/runs/{run_id}/results")).json()["results"][0]
    shown = (await client.get(f"/api/runs/{run_id}/results?include_raw=true")).json()["results"][0]
    assert hidden["raw_response"] is None
    assert shown["raw_response"] == {"segments": [{"document_type": "bill", "pages": "1"}]}

    board = (await client.get(f"/api/runs/{run_id}/leaderboard")).json()
    assert board[0]["accuracy"] == 1.0
    assert board[0]["composite"] == 1.0
    fields = (await client.get(f"/api/runs/{run_id}/field-breakdown?task=segregation")).json()
    assert fields["fields"][0]["per_model"][board[0]["model_id"]] == 1.0
    side = (
        await client.get(
            f"/api/runs/{run_id}/side-by-side?document_id={document_id}&task=segregation"
        )
    ).json()
    assert side["gold"] == {"segments": [{"document_type": "bill", "pages": "1"}]}
    assert side["outputs"][0]["prompt_system"] == "system"
    assert side["outputs"][0]["field_metrics"] == {"segments": "match"}

    events = [
        {
            "type": "cell",
            "run_id": run_id,
            "document_id": document_id,
            "document": "result",
            "model_id": board[0]["model_id"],
            "task": "segregation",
            "status": "running",
        },
        {
            "type": "cell",
            "run_id": run_id,
            "document_id": document_id,
            "document": "result",
            "model_id": board[0]["model_id"],
            "task": "segregation",
            "status": "succeeded",
        },
        {
            "type": "run",
            "run_id": run_id,
            "status": "completed",
            "counts": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0, "pending": 0},
        },
    ]

    class FakeManager:
        async def subscribe(self, requested, *, replay=True):
            assert requested == run_id and replay
            for event in events:
                yield event

    app.dependency_overrides[get_run_manager] = lambda: FakeManager()
    stream = await client.get(f"/api/runs/{run_id}/events")
    assert stream.status_code == 200
    received = [
        json.loads(line.removeprefix("data: "))
        for line in stream.text.splitlines()
        if line.startswith("data:")
    ]
    assert received == events

    import app.scoring.judge as judge_module

    called = []

    async def fake_judge(requested_run, cfg):
        called.append((requested_run, cfg))

    monkeypatch.setattr(judge_module, "judge_run", fake_judge)
    judged = await client.post(
        f"/api/runs/{run_id}/judge",
        json={"model_id": "gemini-3.1-pro", "modes": ["gold_grade", "head_to_head"]},
    )
    assert judged.status_code == 202
    await asyncio.sleep(0)
    assert called[0][0] == run_id
    refreshed = (await client.get(f"/api/runs/{run_id}")).json()
    assert refreshed["run"]["judge_status"] == "completed"

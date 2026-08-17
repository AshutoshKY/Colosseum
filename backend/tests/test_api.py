from __future__ import annotations

import asyncio
import csv
import io
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
    DocumentSample,
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
    assert "merge_bills" in audit["depends_on"]
    assert "merge_bills" in audit["gold_feed_keys"]


async def test_catalog_verify_dynamic_openrouter_model(client, monkeypatch):
    async def fake_verify(model_id: str, thinking_level: str | None = None) -> bool:
        assert model_id == "openrouter/deepseek/deepseek-v4-flash-0731"
        return True

    import app.api.routers.catalog as catalog_module

    monkeypatch.setattr(catalog_module, "_load_verify", lambda: fake_verify)

    # Test encoded slashes URL (from frontend encodeURIComponent)
    res1 = await client.post("/api/catalog/openrouter%2Fdeepseek%2Fdeepseek-v4-flash-0731/verify")
    assert res1.status_code == 200
    assert res1.json()["ok"] is True

    # Test standard slashes URL
    res2 = await client.post("/api/catalog/openrouter/deepseek/deepseek-v4-flash-0731/verify")
    assert res2.status_code == 200
    assert res2.json()["ok"] is True


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
    assert detail["run"]["elapsed_ms"] >= 0
    assert detail["cells"][0]["document_name"] == "result.pdf"
    assert detail["cells"][0]["created_at"]
    assert detail["cells"][0]["completed_at"]

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
    assert side["outputs"][0]["completed_at"]
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
        json={"model_id": "vertex_ai/gemini-2.5-flash", "modes": ["gold_grade", "head_to_head"]},
    )
    assert judged.status_code == 202
    await asyncio.sleep(0)
    assert called[0][0] == run_id
    refreshed = (await client.get(f"/api/runs/{run_id}")).json()
    assert refreshed["run"]["judge_status"] == "completed"


async def test_prompt_version_create_and_activate(client):
    v1_resp = await client.post(
        "/api/prompts/OPD/segregation/versions",
        json={"system_prompt": "v1 sys", "instruction_template": "v1 inst", "activate": True},
    )
    assert v1_resp.status_code == 201
    assert v1_resp.json()["version"] == 1
    assert v1_resp.json()["active"] is True

    v2_resp = await client.post(
        "/api/prompts/OPD/segregation/versions",
        json={"system_prompt": "v2 sys", "instruction_template": "v2 inst", "activate": True},
    )
    assert v2_resp.status_code == 201
    assert v2_resp.json()["version"] == 2
    assert v2_resp.json()["active"] is True

    # Confirm v1 is no longer active
    versions = (await client.get("/api/prompts/OPD/segregation/versions")).json()
    v1_item = next(v for v in versions if v["version"] == 1)
    assert v1_item["active"] is False

    # Now activate v1
    activate_resp = await client.post("/api/prompts/OPD/segregation/versions/1/activate")
    assert activate_resp.status_code == 200
    assert activate_resp.json()["version"] == 1
    assert activate_resp.json()["active"] is True

    # Confirm v1 is active and v2 is inactive
    versions_after = (await client.get("/api/prompts/OPD/segregation/versions")).json()
    v1_after = next(v for v in versions_after if v["version"] == 1)
    v2_after = next(v for v in versions_after if v["version"] == 2)
    assert v1_after["active"] is True
    assert v2_after["active"] is False


async def test_prompt_version_recorded_in_results(client, api_engine):
    doc_res = await client.post(
        "/api/documents", files=[("files", ("claim.pdf", _pdf(), "application/pdf"))]
    )
    doc_id = doc_res.json()[0]["id"]
    run_spec = {
        "name": "prompt-version-test-run",
        "pack": "OPD",
        "selected_tasks": ["segregation"],
        "document_ids": [doc_id],
        "model_ids": ["vertex_ai/gemini-2.5-flash"],
        "upstream_mode": "gold",
    }
    create_res = await client.post("/api/runs", json=run_spec)
    assert create_res.status_code == 202
    run_id = create_res.json()["run_id"]
    results_res = await client.get(f"/api/runs/{run_id}/results")
    assert results_res.status_code == 200
    results_data = results_res.json()["results"]
    assert len(results_data) > 0
    assert "prompt_version" in results_data[0]


async def test_get_document_file(client):
    doc_res = await client.post(
        "/api/documents", files=[("files", ("claim_pdf_test.pdf", _pdf(), "application/pdf"))]
    )
    doc_id = doc_res.json()[0]["id"]
    file_res = await client.get(f"/api/documents/{doc_id}/file")
    assert file_res.status_code == 200
    assert file_res.headers["content-type"] == "application/pdf"
    assert file_res.content == _pdf()


async def test_upload_gold_then_upload_pdf_binds_seamlessly(client):
    # 1. Upload Gold JSON first (creates stub)
    gold_res = await client.post(
        "/api/gold/import",
        files=[
            (
                "file",
                (
                    "gold.json",
                    json.dumps({
                        "document": "data/uploads/order_test_doc.pdf",
                        "tasks": {"audit": {"status": "MATCH"}},
                    }),
                    "application/json",
                ),
            )
        ],
    )
    assert gold_res.status_code == 200

    docs = (await client.get("/api/documents")).json()
    stub = next(d for d in docs if "order_test_doc" in d["filename"])
    assert stub["has_gold"] is True

    # 2. Upload the actual PDF file afterwards
    pdf_res = await client.post(
        "/api/documents",
        files=[("files", ("order_test_doc.pdf", _pdf(), "application/pdf"))],
    )
    assert pdf_res.status_code == 201
    updated_doc = pdf_res.json()[0]
    assert updated_doc["id"] == stub["id"]  # Re-bound to same document
    assert updated_doc["has_gold"] is True
    assert updated_doc["page_count"] == 1

    # 3. View PDF now succeeds
    file_res = await client.get(f"/api/documents/{stub['id']}/file")
    assert file_res.status_code == 200
    assert file_res.headers["content-type"] == "application/pdf"


async def test_upload_pdf_then_upload_gold_binds_seamlessly(client):
    # 1. Upload PDF first
    pdf_res = await client.post(
        "/api/documents",
        files=[("files", ("pdf_first_doc.pdf", _pdf(), "application/pdf"))],
    )
    assert pdf_res.status_code == 201
    doc_id = pdf_res.json()[0]["id"]

    # 2. Upload Gold afterwards
    gold_res = await client.post(
        "/api/gold/import",
        files=[
            (
                "file",
                (
                    "gold.json",
                    json.dumps({
                        "document": "data/uploads/pdf_first_doc.pdf",
                        "tasks": {"nme_analysis": {"nme_total": 0}},
                    }),
                    "application/json",
                ),
            )
        ],
    )
    assert gold_res.status_code == 200

    # 3. Verify gold attached and file accessible
    docs = (await client.get("/api/documents")).json()
    doc = next(d for d in docs if d["id"] == doc_id)
    assert doc["has_gold"] is True

    file_res = await client.get(f"/api/documents/{doc_id}/file")
    assert file_res.status_code == 200


async def test_import_superclaims_csv_with_aggregated_segments(client, tmp_path):
    # Create sample PDF
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    pdf_bytes = BytesIO()
    writer.write(pdf_bytes)

    pdf_res = await client.post(
        "/api/documents",
        files=[("files", ("STEM123_1.pdf", pdf_bytes.getvalue(), "application/pdf"))],
    )
    assert pdf_res.status_code == 201
    doc_id = pdf_res.json()[0]["id"]

    row_payload = {
        "stem": "STEM123_1",
        "claim_id": "STEM123_1",
        "segments": {
            "aggregated_segments": {
                "investigation_report": {"page_ranges": [{"start": 1, "end": 1}], "total_pages": 1},
                "itemized_bill": {
                    "page_ranges": [
                        {"start": 2, "end": 2, "is_pharmacy_bill": False},
                        {"start": 3, "end": 3, "is_pharmacy_bill": True},
                    ],
                    "total_pages": 2,
                },
            }
        },
        "doc_details": {
            "benefits": [{"benefit_id": 101, "benefit_name": "Consultations"}],
        },
        "extracted": {
            "pharmacy_bills": {
                "bills": [{
                    "bill": {"invoice_number": "INV-1", "net_amount": 100.0},
                    "items": [{"item_name": "Medicine", "final_amount": 100.0}],
                }]
            }
        },
    }
    import io
    buf = io.StringIO()
    writer_csv = csv.writer(buf)
    writer_csv.writerow(["json_build_object"])
    writer_csv.writerow([json.dumps(row_payload)])
    csv_content = buf.getvalue()

    gold_res = await client.post(
        "/api/gold/import",
        files=[("file", ("export.csv", csv_content.encode("utf-8"), "text/csv"))],
    )
    assert gold_res.status_code == 200

    gold_get = await client.get(f"/api/gold/{doc_id}")
    assert gold_get.status_code == 200
    tasks = gold_get.json()["tasks"]
    assert "segregation" in tasks
    assert "upstream_benefits" in tasks
    assert "itemized_bills" in tasks
    segments = tasks["segregation"]["segments"]
    assert len(segments) == 3
    assert any(s["document_type"] == "investigation_report" and s["pages"] == "1" for s in segments)
    assert any(s["document_type"] == "itemized_bill" and s["pages"] == "2" and s.get("is_pharmacy_bill") is False for s in segments)
    assert any(s["document_type"] == "itemized_bill" and s["pages"] == "3" and s.get("is_pharmacy_bill") is True for s in segments)


async def test_delete_prompt_version(client):
    # 1. Create v1 and v2
    v1_resp = await client.post(
        "/api/prompts/OPD/segregation/versions",
        json={"system_prompt": "v1 sys", "instruction_template": "v1 inst", "activate": True},
    )
    assert v1_resp.status_code == 201

    v2_resp = await client.post(
        "/api/prompts/OPD/segregation/versions",
        json={"system_prompt": "v2 sys", "instruction_template": "v2 inst", "activate": True},
    )
    assert v2_resp.status_code == 201
    assert v2_resp.json()["version"] == 2
    assert v2_resp.json()["active"] is True

    # 2. Delete v2 (active). v1 should now become active.
    del_v2 = await client.delete("/api/prompts/OPD/segregation/versions/2")
    assert del_v2.status_code == 200
    assert del_v2.json()["status"] == "deleted"

    versions = (await client.get("/api/prompts/OPD/segregation/versions")).json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["active"] is True

    # 3. Delete v1 (last version). Should succeed.
    del_v1 = await client.delete("/api/prompts/OPD/segregation/versions/1")
    assert del_v1.status_code == 200

    versions_empty = (await client.get("/api/prompts/OPD/segregation/versions")).json()
    assert versions_empty == []

    # 4. Deleting non-existent version returns 404
    del_none = await client.delete("/api/prompts/OPD/segregation/versions/999")
    assert del_none.status_code == 404


async def test_delete_document_with_cascades(client, api_engine, tmp_path):
    run_id, doc_id = _seed_run(api_engine, tmp_path)

    # Add ground truth for document
    gt_resp = await client.put(f"/api/gold/{doc_id}", json={"tasks": {"segregation": {"gold": 1}}})
    assert gt_resp.status_code == 200

    # Delete document should cascade-delete cell, result, score, ground truth, and document
    del_resp = await client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Confirm document no longer exists
    assert (await client.get(f"/api/documents/{doc_id}/file")).status_code == 404
    with Session(api_engine) as session:
        assert session.get(DocumentSample, doc_id) is None
        assert session.exec(select(GroundTruth).where(GroundTruth.document_id == doc_id)).all() == []
        assert session.exec(select(RunCell).where(RunCell.document_id == doc_id)).all() == []






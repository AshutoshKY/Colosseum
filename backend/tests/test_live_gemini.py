"""Live Gemini integration test — runs only when Vertex credentials resolve.

Marked ``live``; skipped by default and whenever creds are absent. When it runs it exercises
the full vertical slice (gateway -> Instructor/LiteLLM -> Gemini -> persisted run_result) and
asserts a valid ``ItemizedBillsOutput`` with non-zero token + cost fields.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.core.config import get_settings

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = REPO_ROOT / "data" / "02B-2026-006427.pdf"


def _has_creds() -> bool:
    settings = get_settings()
    if settings.has_vertex_credentials:
        return True
    # Inline service-account JSON path (as used by superclaims-ai).
    creds = os.environ.get("GOOGLE_CLOUD_CREDENTIALS_JSON") or os.environ.get(
        "SUPERCLAIMS_GOOGLE_CREDENTIALS_JSON"
    )
    project = (
        settings.vertexai_project
        or os.environ.get("SUPERCLAIMS_GOOGLE_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    return bool(creds and project)


@pytest.mark.asyncio
async def test_live_itemized_bills_slice(tmp_path):
    if not _has_creds():
        pytest.skip("Vertex credentials not configured; skipping live Gemini test.")
    if not SAMPLE_PDF.is_file():
        pytest.skip(f"Sample PDF missing: {SAMPLE_PDF}")

    from app.db import create_all, get_engine, session_scope
    from app.providers.gateway import ModelGateway
    from app.runner.persistence import persist_cell_result, register_document
    from app.tasks import ITEMIZED_BILLS

    db_url = f"sqlite:///{tmp_path/'live.db'}"
    engine = get_engine(db_url)
    create_all(engine)

    gateway = ModelGateway()
    task = ITEMIZED_BILLS
    task_input = task.build_input(str(SAMPLE_PDF))

    result = await gateway.structured(
        model_id=get_settings().colosseum_default_gemini_model,
        system=task.system_prompt,
        instruction=task.instruction,
        schema=task.schema,
        documents=task_input.documents,
    )

    assert not result.skipped, result.skip_reason
    assert result.valid, result.error
    assert result.parsed is not None
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.cost.total_usd > 0
    assert result.latency_ms > 0

    from app.models import BenchmarkRun, RunCell

    with session_scope(engine) as session:
        doc = register_document(session, str(SAMPLE_PDF))
        run = BenchmarkRun(name="live-test")
        session.add(run)
        session.flush()
        cell = RunCell(run_id=run.id, task=task.name, document_id=doc.id, model_id=result.model_id)
        session.add(cell)
        session.flush()
        row = persist_cell_result(session, cell=cell, result=result)
        assert row.id is not None
        assert row.valid is True
        assert row.total_cost_usd and row.total_cost_usd > 0

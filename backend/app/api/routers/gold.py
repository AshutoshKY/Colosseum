"""Ground-truth read, edit, and bulk import endpoints."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.api.deps import SessionDep
from app.api.schemas import GoldBody, GoldOut
from app.models import DocumentSample, GroundTruth
from app.scoring.ground_truth_import import _resolve_document, _upsert

router = APIRouter(prefix="/gold", tags=["gold"])
REPO_ROOT = Path(__file__).resolve().parents[4]

# Export CSVs pack an entire claim into one ``json_build_object`` cell, exceeding csv's
# default 131072-byte per-field cap; lift it for the simple-CSV parse path too.
csv.field_size_limit(256 * 1024 * 1024)


def _tasks(session: Session, document_id: int) -> dict[str, Any]:
    rows = session.exec(select(GroundTruth).where(GroundTruth.document_id == document_id)).all()
    return {row.task: row.gold for row in rows}


@router.get("/{document_id}", response_model=GoldOut)
def get_gold(document_id: int, session: SessionDep) -> GoldOut:
    if session.get(DocumentSample, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return GoldOut(document_id=document_id, tasks=_tasks(session, document_id))


@router.put("/{document_id}", response_model=GoldOut)
def put_gold(
    document_id: int,
    body: GoldBody,
    session: SessionDep,
) -> GoldOut:
    if session.get(DocumentSample, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    existing = {
        row.task: row
        for row in session.exec(
            select(GroundTruth).where(GroundTruth.document_id == document_id)
        ).all()
    }
    for task, row in existing.items():
        if task not in body.tasks:
            session.delete(row)
    for task, payload in body.tasks.items():
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail=f"Gold for {task!r} must be an object")
        _upsert(session, document_id=document_id, task=task, gold=payload)
    session.commit()
    return GoldOut(document_id=document_id, tasks=body.tasks)


def _json_records(data: bytes) -> list[dict[str, Any]]:
    payload = json.loads(data)
    records = payload if isinstance(payload, list) else [payload]
    if not all(isinstance(row, dict) and "document" in row for row in records):
        raise ValueError("JSON must use the {document, tasks} ground-truth format")
    return records


def _simple_csv_records(data: bytes) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        document = row.get("document") or row.get("path") or row.get("sha256")
        if not document:
            raise ValueError("CSV requires a document/path/sha256 column")
        record = records.setdefault(document, {"document": document, "tasks": {}})
        if row.get("tasks"):
            record["tasks"].update(json.loads(row["tasks"]))
        elif row.get("task") and row.get("gold"):
            record["tasks"][row["task"]] = json.loads(row["gold"])
        else:
            raise ValueError("CSV requires either tasks JSON or task + gold columns")
    return list(records.values())


def _export_csv_records(data: bytes) -> list[dict[str, Any]]:
    path = REPO_ROOT / "scripts" / "convert_gold_exports.py"
    spec = importlib.util.spec_from_file_location("colosseum_convert_gold_exports", path)
    if spec is None or spec.loader is None:
        raise ValueError("scripts/convert_gold_exports.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tempfile.NamedTemporaryFile(suffix=".csv") as handle:
        handle.write(data)
        handle.flush()
        return [
            record
            for row in module.load_rows([Path(handle.name)]).values()
            if (record := module.convert_row(row))
        ]


@router.post("/import")
async def import_gold(
    file: Annotated[list[UploadFile], File(...)],
    session: SessionDep,
) -> dict[str, int]:
    inserted = updated = records_seen = 0
    try:
        for upload in file:
            data = await upload.read()
            try:
                if (upload.filename or "").lower().endswith(".json"):
                    records = _json_records(data)
                elif (upload.filename or "").lower().endswith(".csv"):
                    header = data.splitlines()[0].decode("utf-8-sig") if data else ""
                    records = (
                        _export_csv_records(data)
                        if "json_build_object" in header
                        else _simple_csv_records(data)
                    )
                else:
                    raise ValueError("Only .json and .csv files are supported")
                for record in records:
                    document = _resolve_document(session, str(record["document"]))
                    session.flush()
                    records_seen += 1
                    for task, payload in (record.get("tasks") or {}).items():
                        if not isinstance(payload, dict):
                            raise ValueError(f"Gold for {task!r} must be an object")
                        is_new = _upsert(
                            session,
                            document_id=document.id,
                            task=task,
                            gold=payload,
                        )
                        inserted += int(is_new)
                        updated += int(not is_new)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - surface any parse/convert failure as 422
                raise HTTPException(
                    status_code=422,
                    detail=f"{upload.filename}: {type(exc).__name__}: {exc}",
                ) from exc
        session.commit()
        return {
            "inserted": inserted,
            "updated": updated,
            "files": len(file),
            "records": records_seen,
        }
    finally:
        for upload in file:
            await upload.close()

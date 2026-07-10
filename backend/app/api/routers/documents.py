"""Document upload, inventory, deduplication, and safe deletion."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.api.deps import SessionDep
from app.api.schemas import DocumentOut
from app.models import DocumentSample, GroundTruth, RunCell
from app.runner.persistence import register_document

router = APIRouter(prefix="/documents", tags=["documents"])
REPO_ROOT = Path(__file__).resolve().parents[4]
UPLOAD_DIR = REPO_ROOT / "data" / "uploads"
MAX_FILES = 50
MAX_BYTES = 300 * 1024 * 1024


def _safe_name(filename: str | None) -> str:
    name = Path(filename or "document.pdf").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "document"
    return f"{stem[:180]}.pdf"


def _destination(filename: str) -> Path:
    candidate = UPLOAD_DIR / filename
    index = 1
    while candidate.exists():
        candidate = UPLOAD_DIR / f"{Path(filename).stem}-{index}.pdf"
        index += 1
    return candidate


def _gold_by_document(session: Session) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for row in session.exec(select(GroundTruth)).all():
        out.setdefault(row.document_id, []).append(row.task)
    return {doc_id: sorted(set(keys)) for doc_id, keys in out.items()}


def _document_out(document: DocumentSample, gold_keys: list[str]) -> DocumentOut:
    assert document.id is not None
    return DocumentOut(
        id=document.id,
        filename=Path(document.path).name,
        sha256=document.sha256,
        page_count=document.page_count,
        origin=document.origin,
        has_gold=bool(gold_keys),
        gold_keys=gold_keys,
        gold_summary={key: True for key in gold_keys},
    )


@router.post("", response_model=list[DocumentOut], status_code=201)
async def upload_documents(
    files: Annotated[list[UploadFile], File(...)],
    session: SessionDep,
) -> list[DocumentOut]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one PDF is required")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"At most {MAX_FILES} files per request")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, str, str]] = []
    created: list[Path] = []
    active_temp: Path | None = None
    total = 0
    try:
        for upload in files:
            digest = hashlib.sha256()
            first = await upload.read(5)
            if first != b"%PDF-":
                raise HTTPException(status_code=415, detail=f"{upload.filename}: not a PDF")
            handle = tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=".upload", delete=False)
            temp = Path(handle.name)
            active_temp = temp
            try:
                handle.write(first)
                digest.update(first)
                total += len(first)
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise HTTPException(status_code=413, detail="Upload exceeds 300 MB")
                    digest.update(chunk)
                    handle.write(chunk)
            finally:
                handle.close()
            staged.append((temp, _safe_name(upload.filename), digest.hexdigest()))
            active_temp = None

        gold = _gold_by_document(session)
        output: list[DocumentOut] = []
        for temp, filename, digest in staged:
            existing = session.exec(
                select(DocumentSample).where(DocumentSample.sha256 == digest)
            ).first()
            if existing:
                temp.unlink(missing_ok=True)
                output.append(_document_out(existing, gold.get(existing.id or -1, [])))
                continue
            destination = _destination(filename)
            os.replace(temp, destination)
            created.append(destination)
            document = register_document(session, str(destination), claim_type="OPD")
            document.origin = "upload"
            document.path = str(destination)
            session.add(document)
            session.flush()
            output.append(_document_out(document, []))
        session.commit()
        return output
    except Exception:
        if active_temp:
            active_temp.unlink(missing_ok=True)
        for temp, _, _ in staged:
            temp.unlink(missing_ok=True)
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        for upload in files:
            await upload.close()


@router.get("", response_model=list[DocumentOut])
def list_documents(session: SessionDep) -> list[DocumentOut]:
    gold = _gold_by_document(session)
    documents = session.exec(
        select(DocumentSample).order_by(DocumentSample.created_at.desc())  # type: ignore[union-attr]
    ).all()
    return [_document_out(document, gold.get(document.id or -1, [])) for document in documents]


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    session: SessionDep,
) -> dict[str, str]:
    document = session.get(DocumentSample, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.origin != "upload":
        raise HTTPException(status_code=403, detail="Bundled test documents cannot be deleted")
    in_use = session.exec(select(RunCell.id).where(RunCell.document_id == document_id)).first()
    if in_use is not None:
        raise HTTPException(status_code=409, detail="Document is referenced by a benchmark run")
    for row in session.exec(
        select(GroundTruth).where(GroundTruth.document_id == document_id)
    ).all():
        session.delete(row)
    path = Path(document.path)
    session.delete(document)
    session.commit()
    path.unlink(missing_ok=True)
    return {"status": "deleted"}

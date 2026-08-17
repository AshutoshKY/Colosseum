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
from app.models import DocumentSample, GroundTruth, JudgeComparison, RunCell, RunResult, Score
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
        created_at=document.created_at,
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

            # Check if there is an existing stub document with matching stem/filename from gold import
            stem = Path(filename).stem
            base_stem = stem.rsplit("_", 1)[0] if "_" in stem else stem
            all_docs = session.exec(select(DocumentSample)).all()
            matched_stub: DocumentSample | None = None
            for d in all_docs:
                d_stem = Path(d.path).stem
                d_base = d_stem.rsplit("_", 1)[0] if "_" in d_stem else d_stem
                if (d.sha256.startswith("stub-") or not Path(d.path).is_file()) and (
                    d_stem in {stem, base_stem} or d_base in {stem, base_stem}
                ):
                    matched_stub = d
                    break

            if matched_stub is not None:
                matched_stub.path = str(destination)
                matched_stub.sha256 = digest
                matched_stub.origin = "upload"
                try:
                    from app.utils.pdf import page_count
                    matched_stub.page_count = page_count(str(destination))
                except Exception:
                    pass
                session.add(matched_stub)
                session.flush()
                output.append(_document_out(matched_stub, gold.get(matched_stub.id or -1, [])))
            else:
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

    # Clean up any run results and scores associated with run cells for this document
    cell_ids = session.exec(select(RunCell.id).where(RunCell.document_id == document_id)).all()
    if cell_ids:
        result_ids = session.exec(select(RunResult.id).where(RunResult.cell_id.in_(cell_ids))).all()
        if result_ids:
            for score in session.exec(select(Score).where(Score.result_id.in_(result_ids))).all():
                session.delete(score)
            for result in session.exec(select(RunResult).where(RunResult.id.in_(result_ids))).all():
                session.delete(result)
        for cell in session.exec(select(RunCell).where(RunCell.id.in_(cell_ids))).all():
            session.delete(cell)

    # Clean up judge comparisons for this document
    for comparison in session.exec(
        select(JudgeComparison).where(JudgeComparison.document_id == document_id)
    ).all():
        session.delete(comparison)

    # Clean up ground truth
    for row in session.exec(
        select(GroundTruth).where(GroundTruth.document_id == document_id)
    ).all():
        session.delete(row)

    path = Path(document.path)
    session.delete(document)
    session.commit()
    path.unlink(missing_ok=True)
    return {"status": "deleted"}


from fastapi.responses import FileResponse


@router.get("/{document_id}/file")
def get_document_file(document_id: int, session: SessionDep):
    document = session.get(DocumentSample, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(document.path)
    if not path.is_file():
        # Check fallback locations
        stem = path.stem
        base_stem = stem.rsplit("_", 1)[0] if "_" in stem else stem
        candidates = [
            REPO_ROOT / path,
            UPLOAD_DIR / path.name,
            REPO_ROOT / "test-docs" / path.name,
            UPLOAD_DIR / f"{stem}.pdf",
            REPO_ROOT / "test-docs" / f"{stem}.pdf",
            UPLOAD_DIR / f"{base_stem}.pdf",
            REPO_ROOT / "test-docs" / f"{base_stem}.pdf",
            UPLOAD_DIR / f"{base_stem}_1.pdf",
            REPO_ROOT / "test-docs" / f"{base_stem}_1.pdf",
            UPLOAD_DIR / f"{base_stem}-1.pdf",
            REPO_ROOT / "test-docs" / f"{base_stem}-1.pdf",
        ]
        found = next((p for p in candidates if p.is_file()), None)
        if found:
            path = found
        else:
            raise HTTPException(
                status_code=404,
                detail=f"File {path.name} not found on disk. Please upload the PDF file ({path.name}) using 'Drop PDFs here' above.",
            )
    return FileResponse(
        path=path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


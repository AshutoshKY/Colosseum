"""Ground-truth importer + CLI.

Loads per-document, per-task gold JSON into the ``ground_truth`` table so ``field_metrics.py``
can score accuracy/precision/recall and the scoreboard can rank correctness. The expected
baseline format is documented in ``docs/ground-truth-format.md``.

Accepted input (a single JSON file, or a directory of them):

  {
    "document": "test-docs/REQ65CYP9E0_1.pdf",   # path OR sha256 of a registered document
    "tasks": {
      "segregation": { ...gold DocumentSegregatorOutput... },
      "nme_analysis": { ...gold NmeAnalysisOutput... }
    }
  }

A list of such objects is also accepted. Each (document, task) upserts one ``ground_truth`` row.

CLI:
    uv run python -m app.scoring.ground_truth_import path/to/gold.json
    uv run python -m app.scoring.ground_truth_import path/to/gold_dir/ --db-url sqlite:///gt.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.db import create_all, get_engine, session_scope
from app.models import DocumentSample, GroundTruth
from app.runner.persistence import register_document

logger = get_logger(__name__)


def _resolve_document(session: Session, ref: str) -> DocumentSample:
    """Resolve a document by sha256, then by exact path, then by stem match, then register if file exists."""
    by_hash = session.exec(select(DocumentSample).where(DocumentSample.sha256 == ref)).first()
    if by_hash:
        return by_hash
    by_path = session.exec(select(DocumentSample).where(DocumentSample.path == ref)).first()
    if by_path:
        return by_path
    stem = Path(ref).stem
    base_stem = stem.rsplit("_", 1)[0] if "_" in stem else stem
    for doc in session.exec(select(DocumentSample)).all():
        doc_stem = Path(doc.path).stem
        doc_base = doc_stem.rsplit("_", 1)[0] if "_" in doc_stem else doc_stem
        if doc_stem in {stem, base_stem} or doc_base in {stem, base_stem}:
            return doc
    if Path(ref).is_file():
        return register_document(session, ref, claim_type="OPD")
    stub = DocumentSample(path=ref, sha256=f"stub-{stem}", claim_type="OPD", page_count=None)
    session.add(stub)
    session.flush()
    return stub



def _upsert(session: Session, *, document_id: int, task: str, gold: dict[str, Any]) -> bool:
    existing = session.exec(
        select(GroundTruth).where(
            GroundTruth.document_id == document_id, GroundTruth.task == task
        )
    ).first()
    if existing:
        existing.gold = gold
        session.add(existing)
        return False
    session.add(GroundTruth(document_id=document_id, task=task, gold=gold))
    return True


def _iter_records(payload: Any):
    if isinstance(payload, list):
        yield from payload
    else:
        yield payload


def import_ground_truth(paths: list[str], *, db_url: str | None = None) -> dict[str, int]:
    """Import gold JSON file(s)/dir(s) into ``ground_truth``. Returns counts."""
    engine = get_engine(db_url) if db_url else get_engine()
    if db_url:
        create_all(engine)

    files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(p)

    inserted = updated = 0
    with session_scope(engine) as session:
        for fp in files:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            for rec in _iter_records(payload):
                doc = _resolve_document(session, rec["document"])
                session.flush()
                for task, gold in (rec.get("tasks") or {}).items():
                    is_new = _upsert(session, document_id=doc.id, task=task, gold=gold)
                    inserted += int(is_new)
                    updated += int(not is_new)
    logger.info("ground-truth import: %d inserted, %d updated from %d file(s)", inserted, updated, len(files))
    return {"inserted": inserted, "updated": updated, "files": len(files)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import per-document/per-task gold JSON into ground_truth.")
    parser.add_argument("paths", nargs="+", help="gold JSON file(s) or directory(ies)")
    parser.add_argument("--db-url", dest="db_url", default=None, help="override DB URL (e.g. sqlite)")
    args = parser.parse_args(argv)
    try:
        counts = import_ground_truth(args.paths, db_url=args.db_url)
    except Exception as exc:  # noqa: BLE001
        print(f"import failed: {exc}", file=sys.stderr)
        return 1
    print(f"ground-truth import: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

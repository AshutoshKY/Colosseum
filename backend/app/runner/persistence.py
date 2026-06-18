"""Persistence helpers: register a document sample, write a full ``run_result`` row.

A ``GatewayResult`` carries everything the data model needs; this module maps it onto the
``run_cell`` -> ``run_result`` tables ("store everything").
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, select

from app.models import DocumentSample, RunCell, RunResult, RunStatus
from app.providers.gateway import GatewayResult
from app.utils.pdf import page_count


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def register_document(
    session: Session, path: str, *, claim_type: str | None = None
) -> DocumentSample:
    """Idempotently register a document sample by content hash."""
    digest = _sha256(path)
    existing = session.exec(select(DocumentSample).where(DocumentSample.sha256 == digest)).first()
    if existing:
        return existing
    try:
        pages = page_count(path)
    except Exception:
        pages = None
    doc = DocumentSample(path=path, claim_type=claim_type, page_count=pages, sha256=digest)
    session.add(doc)
    session.flush()
    return doc


def _to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def persist_cell_result(
    session: Session,
    *,
    cell: RunCell,
    result: GatewayResult,
) -> RunResult:
    """Map a ``GatewayResult`` onto a ``run_result`` row and update the cell status."""
    if result.skipped:
        cell.status = RunStatus.skipped
        cell.skip_reason = result.skip_reason
    else:
        cell.status = RunStatus.succeeded if result.valid else RunStatus.failed
    session.add(cell)
    session.flush()

    parsed_json = result.parsed.model_dump(mode="json") if result.parsed is not None else None
    cost = result.cost

    row = RunResult(
        cell_id=cell.id,
        raw_response=result.raw_response,
        parsed_output=parsed_json,
        valid=result.valid,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        thinking_tokens=result.usage.thinking_tokens,
        cached_tokens=result.usage.cached_tokens,
        total_tokens=result.usage.total_tokens,
        est_input_cost=_to_float(cost.input_usd),
        est_output_cost=_to_float(cost.output_usd),
        est_cache_cost=_to_float(cost.cache_usd),
        est_thinking_cost=_to_float(cost.thinking_usd),
        total_cost_usd=_to_float(cost.total_usd),
        pricing_version=cost.pricing_version,
        latency_ms=result.latency_ms,
        retries=result.retries,
        error=result.error,
        usage_raw=result.usage_raw,
        structured_method=result.structured_method,
        endpoint=result.endpoint,
    )
    session.add(row)
    session.flush()
    return row

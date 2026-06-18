"""Phase-1 vertical slice.

Runs ``itemized_bills`` on one PDF with one Gemini Vertex model through ``ModelGateway`` and
persists a full ``run_result`` (tokens, cost, latency, parsed output). Proves the end-to-end
provider-core path.

Usage:
    uv run python -m app.runner.vertical_slice data/02B-2026-006427.pdf
    uv run python -m app.runner.vertical_slice data/02B-2026-006427.pdf --model vertex_ai/gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import create_all, get_engine, session_scope
from app.models import BenchmarkRun, RunCell
from app.providers.gateway import ModelGateway
from app.runner.persistence import persist_cell_result, register_document
from app.tasks import ITEMIZED_BILLS

logger = get_logger(__name__)


async def run_slice(
    pdf_path: str,
    *,
    model_id: str | None = None,
    page_ranges: str | None = None,
    db_url: str | None = None,
) -> int:
    settings = get_settings()
    model_id = model_id or settings.colosseum_default_gemini_model
    task = ITEMIZED_BILLS

    engine = get_engine(db_url) if db_url else get_engine()
    if db_url:  # tests / sqlite: bootstrap schema (prod uses alembic).
        create_all(engine)

    gateway = ModelGateway()
    task_input = task.build_input(pdf_path, page_ranges=page_ranges)

    logger.info("running %s on %s with %s", task.name, pdf_path, model_id)
    result = await gateway.structured(
        model_id=model_id,
        system=task.system_prompt,
        instruction=task.instruction,
        schema=task.schema,
        documents=task_input.documents,
    )

    with session_scope(engine) as session:
        doc = register_document(session, pdf_path, claim_type="health_claim")
        run = BenchmarkRun(name=f"vertical-slice:{task.name}")
        session.add(run)
        session.flush()
        cell = RunCell(
            run_id=run.id,
            task=task.name,
            document_id=doc.id,
            model_id=model_id,
            config={},
        )
        session.add(cell)
        session.flush()
        row = persist_cell_result(session, cell=cell, result=result)
        result_id = row.id

    _print_summary(model_id, result, result_id)
    return 0 if (result.valid or result.skipped) else 1


def _print_summary(model_id: str, result, result_id: int | None) -> None:  # type: ignore[no-untyped-def]
    print("\n=== Vertical slice result ===")
    print(f"model:            {model_id}")
    print(f"run_result.id:    {result_id}")
    print(f"valid:            {result.valid}")
    print(f"skipped:          {result.skipped} ({result.skip_reason})")
    print(f"structured_method:{result.structured_method}")
    print(f"latency_ms:       {result.latency_ms}")
    print(f"retries:          {result.retries}")
    u = result.usage
    print(
        f"tokens:           input={u.input_tokens} output={u.output_tokens} "
        f"thinking={u.thinking_tokens} cached={u.cached_tokens} total={u.total_tokens}"
    )
    c = result.cost
    print(
        f"cost_usd:         input={c.input_usd} output={c.output_usd} "
        f"cache={c.cache_usd} thinking={c.thinking_usd} TOTAL={c.total_usd} "
        f"(pricing={c.pricing_version})"
    )
    if result.parsed is not None:
        bills = getattr(result.parsed, "bills", [])
        items = sum(len(b.items) for b in bills)
        print(f"parsed:           {len(bills)} bill(s), {items} line item(s)")
    if result.error:
        print(f"error:            {result.error}")
    print("=============================\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Colosseum Phase-1 vertical slice")
    parser.add_argument("pdf", help="path to a sample claim PDF")
    parser.add_argument("--model", dest="model", default=None, help="LiteLLM model id")
    parser.add_argument("--pages", dest="pages", default=None, help="1-based page ranges, e.g. '1,3-5'")
    parser.add_argument("--db-url", dest="db_url", default=None, help="override DB URL (e.g. sqlite)")
    args = parser.parse_args(argv)

    if not Path(args.pdf).is_file():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    return asyncio.run(
        run_slice(args.pdf, model_id=args.model, page_ranges=args.pages, db_url=args.db_url)
    )


if __name__ == "__main__":
    raise SystemExit(main())

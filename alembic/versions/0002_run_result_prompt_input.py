"""Add prompt/structured-input columns to run_result (Phase 2.5: store everything).

Persists the exact prompt (system + instruction) and document count sent to the model on every
call, alongside the raw + parsed output, tokens, cost, latency, and retries already stored.

The 0001 baseline emits the schema from ``SQLModel.metadata`` (``create_all``), so on a fresh DB
these columns already exist after 0001. This migration is therefore idempotent: it only adds a
column when it is missing, so it is a no-op on a fresh DB and a real upgrade for any DB that was
stamped at 0001 before these model fields landed.

Revision ID: 0002_run_result_prompt_input
Revises: 0001_initial
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_run_result_prompt_input"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = {
    "prompt_system": sa.Column("prompt_system", sa.Text(), nullable=True),
    "prompt_instruction": sa.Column("prompt_instruction", sa.Text(), nullable=True),
    "document_count": sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
}


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    have = _existing_columns("run_result")
    for name, column in _NEW_COLUMNS.items():
        if name not in have:
            op.add_column("run_result", column)


def downgrade() -> None:
    have = _existing_columns("run_result")
    for name in reversed(list(_NEW_COLUMNS)):
        if name in have:
            op.drop_column("run_result", name)

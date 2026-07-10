"""Add persisted judge comparisons.

Revision ID: 0005_judge
Revises: 0004_run_spec
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_judge"
down_revision: str | None = "0004_run_spec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "judgecomparison" in _tables():
        return
    op.create_table(
        "judgecomparison",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("benchmark_run.id"), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("document_sample.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("judge_model", sa.String(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("run_id", "task_name", "document_id", "mode", "judge_model"):
        op.create_index(f"ix_judgecomparison_{name}", "judgecomparison", [name])


def downgrade() -> None:
    if "judgecomparison" in _tables():
        op.drop_table("judgecomparison")

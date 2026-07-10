"""Persist the verbatim run specification and task-pack name.

Revision ID: 0004_run_spec
Revises: 0003_prompt_versions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_run_spec"
down_revision: str | None = "0003_prompt_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("benchmark_run")}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE runstatus ADD VALUE IF NOT EXISTS 'completed'")
        op.execute("ALTER TYPE runstatus ADD VALUE IF NOT EXISTS 'cancelled'")
    have = _columns()
    if "spec" not in have:
        op.add_column("benchmark_run", sa.Column("spec", JSONB, nullable=True))
    if "pack" not in have:
        op.add_column(
            "benchmark_run",
            sa.Column("pack", sa.String(), nullable=False, server_default="OPD"),
        )
        op.create_index("ix_benchmark_run_pack", "benchmark_run", ["pack"])


def downgrade() -> None:
    have = _columns()
    if "pack" in have:
        op.drop_index("ix_benchmark_run_pack", table_name="benchmark_run")
        op.drop_column("benchmark_run", "pack")
    if "spec" in have:
        op.drop_column("benchmark_run", "spec")

"""Add prompt_version column to run_result.

Revision ID: 0008_run_result_prompt_version
Revises: 0007_failed_run_status
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_run_result_prompt_version"
down_revision: str | None = "0007_failed_run_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    have = _existing_columns("run_result")
    if "prompt_version" not in have:
        op.add_column("run_result", sa.Column("prompt_version", sa.Text(), nullable=True))


def downgrade() -> None:
    have = _existing_columns("run_result")
    if "prompt_version" in have:
        op.drop_column("run_result", "prompt_version")

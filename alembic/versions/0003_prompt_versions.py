"""Add versioned prompt storage.

Revision ID: 0003_prompt_versions
Revises: 0002_run_result_prompt_input
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_prompt_versions"
down_revision: str | None = "0002_run_result_prompt_input"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "promptversion" in _tables():
        return
    op.create_table(
        "promptversion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pack", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("instruction_template", sa.Text(), nullable=False),
        sa.Column("source_repo", sa.String(), nullable=True),
        sa.Column("source_branch", sa.String(), nullable=True),
        sa.Column("source_path", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "pack", "task_name", "version", name="uq_promptversion_pack_task_version"
        ),
    )
    op.create_index("ix_promptversion_pack", "promptversion", ["pack"])
    op.create_index("ix_promptversion_task_name", "promptversion", ["task_name"])
    op.create_index("ix_promptversion_active", "promptversion", ["active"])
    op.create_index(
        "uq_promptversion_active",
        "promptversion",
        ["pack", "task_name"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active = 1"),
    )


def downgrade() -> None:
    if "promptversion" in _tables():
        op.drop_table("promptversion")

"""Initial schema — create all Colosseum tables.

Rather than hand-transcribe every column (and risk drift from the SQLModel definitions),
this migration emits the full schema from ``SQLModel.metadata``. The models are the source of
truth; this keeps the migration in lock-step with them for the Phase-1 baseline.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

# Import models so every table is registered on SQLModel.metadata.
import app.models  # noqa: F401
from sqlmodel import SQLModel

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind)

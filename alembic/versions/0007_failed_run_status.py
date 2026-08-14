"""Correct legacy completed runs that never made a model call.

Revision ID: 0007_failed_run_status
Revises: 0006_document_origin
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_failed_run_status"
down_revision: str | None = "0006_document_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A completed run with cells but no successful or failed cell only represents a capability
    # gate; its worker ended but it produced no model result.  Surface it as failed.
    op.execute(
        """
        UPDATE benchmark_run AS run
        SET status = 'failed'
        WHERE run.status = 'completed'
          AND EXISTS (SELECT 1 FROM run_cell cell WHERE cell.run_id = run.id)
          AND NOT EXISTS (
              SELECT 1 FROM run_cell cell
              WHERE cell.run_id = run.id AND cell.status IN ('succeeded', 'failed')
          )
        """
    )


def downgrade() -> None:
    # Status history cannot be safely inferred in reverse.
    pass

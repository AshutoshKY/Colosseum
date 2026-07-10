"""Record whether a document came from test-docs or an upload.

Revision ID: 0006_document_origin
Revises: 0005_judge
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_document_origin"
down_revision: str | None = "0005_judge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("document_sample")}


def upgrade() -> None:
    if "origin" not in _columns():
        op.add_column(
            "document_sample",
            sa.Column("origin", sa.String(), nullable=False, server_default="test-docs"),
        )
        op.create_index("ix_document_sample_origin", "document_sample", ["origin"])


def downgrade() -> None:
    if "origin" in _columns():
        op.drop_index("ix_document_sample_origin", table_name="document_sample")
        op.drop_column("document_sample", "origin")

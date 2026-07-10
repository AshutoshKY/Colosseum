"""Versioned prompt templates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models._base import created_at_field


class PromptVersion(SQLModel, table=True):
    __tablename__ = "promptversion"
    __table_args__ = (
        UniqueConstraint("pack", "task_name", "version", name="uq_promptversion_pack_task_version"),
        Index(
            "uq_promptversion_active",
            "pack",
            "task_name",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    pack: str = Field(index=True)
    task_name: str = Field(index=True)
    version: int
    system_prompt: str
    instruction_template: str
    source_repo: str | None = None
    source_branch: str | None = None
    source_path: str | None = None
    active: bool = Field(default=True, index=True)
    created_at: Any = created_at_field()

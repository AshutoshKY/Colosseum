"""Shared column types and mixins for ORM tables."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

# Use JSONB on Postgres; SQLAlchemy falls back to JSON on SQLite for offline tests.
JSONB_VARIANT = JSONB(none_as_null=True).with_variant(
    __import__("sqlalchemy").JSON(none_as_null=True), "sqlite"
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def created_at_field() -> object:
    return Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

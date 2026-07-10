"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from app.db import get_engine
from app.runner.run_manager import RunManager, run_manager


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_run_manager() -> RunManager:
    return run_manager


SessionDep = Annotated[Session, Depends(get_session)]
RunManagerDep = Annotated[RunManager, Depends(get_run_manager)]

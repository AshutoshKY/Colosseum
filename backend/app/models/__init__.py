"""SQLModel ORM tables — the durable "store everything" record.

Importing this package registers every table on ``SQLModel.metadata`` so Alembic
autogenerate and ``create_all`` can see them.
"""

from __future__ import annotations

from app.models.benchmark import BenchmarkRun, RunCell, RunResult, RunStatus
from app.models.catalog import ModelCatalog
from app.models.document import DocumentSample
from app.models.ground_truth import GroundTruth
from app.models.score import Score

__all__ = [
    "ModelCatalog",
    "DocumentSample",
    "BenchmarkRun",
    "RunCell",
    "RunResult",
    "RunStatus",
    "Score",
    "GroundTruth",
]

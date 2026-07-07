"""Scoring: deterministic field metrics + composite scoreboard + ground-truth ingestion."""

from __future__ import annotations

from app.scoring.field_metrics import FieldMetrics, score_against_gold
from app.scoring.scoreboard import ScoreboardRow, build_scoreboard

__all__ = [
    "FieldMetrics",
    "score_against_gold",
    "ScoreboardRow",
    "build_scoreboard",
]

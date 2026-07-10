"""Structured outputs returned by the LLM-as-judge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FieldVerdict(BaseModel):
    field_path: str
    verdict: Literal[
        "match", "acceptable_variant", "mismatch", "missing", "hallucinated"
    ]
    explanation: str
    gold_value: str | None = None
    predicted_value: str | None = None


class JudgeGradeOutput(BaseModel):
    overall_score: float = Field(ge=0, le=1)
    field_verdicts: list[FieldVerdict] = Field(default_factory=list)
    summary: str


class CandidateRank(BaseModel):
    candidate: str
    rank: int = Field(ge=1)
    strengths: str
    weaknesses: str


class JudgeRankingOutput(BaseModel):
    ranking: list[CandidateRank]
    rationale: str
    confidence: Literal["low", "medium", "high"]

"""Composite scoreboard — ranks models per (task) by a multi-signal composite.

composite = w_acc * accuracy_or_validity
          + w_cost * cost_efficiency        (cheaper -> higher, normalized within the group)
          + w_lat  * latency_efficiency     (faster  -> higher, normalized within the group)

When ground truth exists for a (document, task), ``accuracy`` is the field-metric accuracy;
otherwise the structural ``validity`` (1.0 if the output parsed against the schema, else 0.0)
stands in. Skipped cells (capability-gated, e.g. text-only model on an image task) are excluded
from ranking and surfaced separately as "not applicable".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# default composite weights (accuracy/validity dominates, then cost, then latency).
W_ACC = 0.6
W_COST = 0.25
W_LAT = 0.15


@dataclass
class ScoreboardRow:
    task: str
    model_id: str
    valid: bool
    accuracy: float | None  # field-metric accuracy when ground truth exists, else None
    total_cost_usd: float
    latency_ms: int
    composite: float = 0.0
    rank: int | None = None
    skipped: bool = False
    skip_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_id": self.model_id,
            "valid": self.valid,
            "accuracy": self.accuracy,
            "total_cost_usd": self.total_cost_usd,
            "latency_ms": self.latency_ms,
            "composite": round(self.composite, 4),
            "rank": self.rank,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


def _inverse_norm(values: list[float]) -> list[float]:
    """Map values so that smaller -> 1.0 and larger -> 0.0 within the group (cost/latency)."""
    finite = [v for v in values if v and v > 0]
    if not finite:
        return [1.0 for _ in values]
    lo, hi = min(finite), max(finite)
    if hi == lo:
        return [1.0 for _ in values]
    out = []
    for v in values:
        if not v or v <= 0:
            out.append(1.0)  # free/instant -> best
        else:
            out.append(1.0 - (v - lo) / (hi - lo))
    return out


def build_scoreboard(rows: list[ScoreboardRow]) -> list[ScoreboardRow]:
    """Compute composites per task group and assign ranks. Mutates + returns ``rows``."""
    # group by task
    by_task: dict[str, list[ScoreboardRow]] = {}
    for r in rows:
        by_task.setdefault(r.task, []).append(r)

    for task_rows in by_task.values():
        scored = [r for r in task_rows if not r.skipped]
        if not scored:
            continue
        costs = _inverse_norm([r.total_cost_usd for r in scored])
        lats = _inverse_norm([float(r.latency_ms) for r in scored])
        for r, ceff, leff in zip(scored, costs, lats, strict=True):
            acc = r.accuracy if r.accuracy is not None else (1.0 if r.valid else 0.0)
            r.composite = W_ACC * acc + W_COST * ceff + W_LAT * leff
        scored.sort(key=lambda r: r.composite, reverse=True)
        for i, r in enumerate(scored, start=1):
            r.rank = i

    return rows

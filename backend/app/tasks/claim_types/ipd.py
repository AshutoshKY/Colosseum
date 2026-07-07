"""IPD claim-type placeholders: CL (cashless) and RM (reimbursement).

Scaffolded but NOT built out in Phase 2. They mirror the shape of superclaims-ai's
``config/profiles/base/cl.toml`` and ``rm.toml`` (RM extends CL) so the task pack can be filled
in later, but every accessor raises ``NotImplementedError`` for now.

The node lists below are documentation of the intended IPD pipeline (from cl.toml) — they are
the agents an IPD task pack would vendor in a future phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.tasks.base import Task


@dataclass(frozen=True)
class IpdClaimTypeStub:
    """A scaffolded IPD claim type. Accessors raise until the pack is built."""

    claim_type: str  # "CL" or "RM"
    description: str
    # Intended pipeline agents (mirrors base/cl.toml node order); not implemented yet.
    planned_nodes: tuple[str, ...] = field(default_factory=tuple)
    extends: str | None = None

    def task_pack(self) -> dict[str, Task]:
        raise NotImplementedError(
            f"IPD claim type {self.claim_type!r} ({self.description}) is a Phase-2 placeholder "
            f"and is not implemented yet. Planned pipeline: {', '.join(self.planned_nodes)}."
        )

    def get_task(self, name: str) -> Task:  # noqa: ARG002
        raise NotImplementedError(
            f"IPD claim type {self.claim_type!r} is not implemented yet (placeholder)."
        )


CL_CLAIM_TYPE = IpdClaimTypeStub(
    claim_type="CL",
    description="IPD Cashless",
    planned_nodes=(
        "segregation",
        "claim_form",
        "discharge_summary",
        "itemized_bills",
        "consolidated_bills",
        "merge_bills",
        "items_categorisation",
        "nme_analysis",
        "audit",
    ),
)

RM_CLAIM_TYPE = IpdClaimTypeStub(
    claim_type="RM",
    description="IPD Reimbursement",
    extends="CL",
    planned_nodes=CL_CLAIM_TYPE.planned_nodes,
)

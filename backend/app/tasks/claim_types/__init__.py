"""Claim-type layer: maps a claim type to its task pack.

Mirrors superclaims-ai's claim-type model
(``DEFAULT_CLAIM_TYPE_BY_PROJECT = {"ekincare": "OPD"}``,
``CLAIM_TYPE_ALIASES = {"IPD": "CL", "MR": "RM"}``):

* ``OPD`` is fully wired (the Phase-2 task pack).
* ``IPD`` resolves to its sub-types ``CL`` (cashless) and ``RM`` (reimbursement), which are
  scaffolded as placeholders that raise ``NotImplementedError`` — Phase 2 does NOT build their
  OPD-equivalent logic.
"""

from __future__ import annotations

from app.tasks.base import Task
from app.tasks.claim_types.ipd import CL_CLAIM_TYPE, RM_CLAIM_TYPE, IpdClaimTypeStub
from app.tasks.opd import OPD_TASKS

# IPD aliases -> sub-type profiles (cashless / reimbursement).
CLAIM_TYPE_ALIASES = {"IPD": "CL", "MR": "RM"}

# project -> default claim type (ekincare runs OPD).
DEFAULT_CLAIM_TYPE_BY_PROJECT = {"ekincare": "OPD"}


def resolve_claim_type(claim_type: str) -> str:
    """Resolve aliases (IPD -> CL, MR -> RM); return the canonical claim type."""
    key = claim_type.strip().upper()
    return CLAIM_TYPE_ALIASES.get(key, key)


def get_task_pack(claim_type: str) -> dict[str, Task]:
    """Return the task pack for a claim type. OPD is wired; CL/RM stubs raise NotImplementedError."""
    resolved = resolve_claim_type(claim_type)
    if resolved == "OPD":
        return OPD_TASKS
    if resolved == "CL":
        return CL_CLAIM_TYPE.task_pack()
    if resolved == "RM":
        return RM_CLAIM_TYPE.task_pack()
    raise KeyError(f"Unknown claim type: {claim_type!r} (resolved {resolved!r}).")


__all__ = [
    "CLAIM_TYPE_ALIASES",
    "DEFAULT_CLAIM_TYPE_BY_PROJECT",
    "resolve_claim_type",
    "get_task_pack",
    "IpdClaimTypeStub",
    "CL_CLAIM_TYPE",
    "RM_CLAIM_TYPE",
]

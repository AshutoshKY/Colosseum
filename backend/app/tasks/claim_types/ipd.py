"""IPD claim-type profiles backed by the healthpay task pack."""

from __future__ import annotations

from dataclasses import dataclass

from app.tasks.base import Task, TaskPack
from app.tasks.ipd import get_ipd_pack


@dataclass(frozen=True)
class IpdClaimType:
    claim_type: str
    description: str

    def task_pack(self) -> TaskPack:
        return get_ipd_pack(self.claim_type)

    def get_task(self, name: str) -> Task:
        return self.task_pack().tasks[name]


CL_CLAIM_TYPE = IpdClaimType("CL", "IPD Cashless")
RM_CLAIM_TYPE = IpdClaimType("RM", "IPD Reimbursement")
PP_CLAIM_TYPE = IpdClaimType("PP", "IPD Pre/Post hospitalization")

# Backward-compatible import name used by older callers.
IpdClaimTypeStub = IpdClaimType

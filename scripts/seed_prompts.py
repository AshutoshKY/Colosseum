"""Seed version 1 prompt rows from the task-pack constants."""

from __future__ import annotations

from app.db import get_engine, session_scope
from app.models import PromptVersion
from app.runner.spec import task_pack_for
from sqlmodel import Session, select


def _provenance(pack: str, task_name: str) -> tuple[str, str, str]:
    if pack == "IPD":
        return "healthpay-ai", "test-fhpl", "healthpay/backend/app/lang_graph/prompts/"
    if task_name in {
        "policy_extraction",
        "benefit_plan",
        "claim_form",
        "prescription",
        "identity_document",
        "cheque_bank",
        "extract_icd_codes",
        "patient_summary",
    }:
        return "superclaims-ai", "test-ekincare-v2", "backend/app/lang_graph/prompts/"
    return "healthpay-ai", "test-fhpl", "healthpay/backend/app/lang_graph/prompts/"


def seed_prompts(session: Session) -> int:
    inserted = 0
    for pack_name in ("OPD", "IPD"):
        try:
            pack = task_pack_for(pack_name)
        except NotImplementedError:
            continue
        for task in pack.tasks.values():
            exists = session.exec(
                select(PromptVersion).where(
                    PromptVersion.pack == pack_name,
                    PromptVersion.task_name == task.name,
                    PromptVersion.version == 1,
                )
            ).first()
            if exists:
                continue
            repo, branch, path = _provenance(pack_name, task.name)
            session.add(
                PromptVersion(
                    pack=pack_name,
                    task_name=task.name,
                    version=1,
                    system_prompt=task.system_prompt,
                    instruction_template=task.instruction,
                    source_repo=repo,
                    source_branch=branch,
                    source_path=path,
                    active=True,
                )
            )
            inserted += 1
    session.flush()
    return inserted


def main() -> None:
    with session_scope(get_engine()) as session:
        print(f"Inserted {seed_prompts(session)} prompt versions")


if __name__ == "__main__":
    main()

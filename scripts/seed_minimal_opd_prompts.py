"""Add inactive Updates Minimal prompt versions for every model-backed OPD task."""

from __future__ import annotations

from app.db import get_engine, session_scope
from app.models import PromptVersion
from app.tasks.prompts.opd_minimal import MINIMAL_OPD_PROMPTS
from sqlmodel import Session, func, select


def seed_minimal_opd_prompts(session: Session) -> int:
    inserted = 0
    for task_name, (system_prompt, instruction_template) in MINIMAL_OPD_PROMPTS.items():
        existing = session.exec(
            select(PromptVersion).where(
                PromptVersion.pack == "OPD",
                PromptVersion.task_name == task_name,
                PromptVersion.source_branch == "updates-minimal",
            )
        ).first()
        if existing:
            if (
                existing.system_prompt != system_prompt
                or existing.instruction_template != instruction_template
            ):
                existing.system_prompt = system_prompt
                existing.instruction_template = instruction_template
                session.add(existing)
                inserted += 1
            continue
        latest = session.exec(
            select(func.max(PromptVersion.version)).where(
                PromptVersion.pack == "OPD",
                PromptVersion.task_name == task_name,
            )
        ).one()
        session.add(
            PromptVersion(
                pack="OPD",
                task_name=task_name,
                version=(latest or 0) + 1,
                system_prompt=system_prompt,
                instruction_template=instruction_template,
                source_repo="Colosseum",
                source_branch="updates-minimal",
                source_path="backend/app/tasks/prompts/opd_minimal.py",
                active=False,
            )
        )
        inserted += 1
    session.flush()
    return inserted


def main() -> None:
    with session_scope(get_engine()) as session:
        print(f"Inserted {seed_minimal_opd_prompts(session)} inactive minimal OPD prompt versions")


if __name__ == "__main__":
    main()

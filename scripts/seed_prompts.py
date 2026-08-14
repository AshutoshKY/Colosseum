"""Seed version 1 prompt rows from the task-pack constants."""

from __future__ import annotations

from app.db import get_engine, session_scope
from app.models import PromptVersion
from app.runner.spec import task_pack_for
from sqlmodel import Session, select


def _provenance(pack: str, task_name: str) -> tuple[str, str, str]:
    if pack == "IPD":
        return "healthpay-ai", "test-fhpl", "healthpay/backend/app/lang_graph/prompts/"
    if pack == "OPD":
        return "superclaims-ai", "test-ekincare-v2", "backend/app/lang_graph/prompts/"
    raise ValueError(f"Unknown task pack: {pack}")


def seed_prompts(session: Session) -> int:
    inserted = 0
    for pack_name in ("OPD", "IPD"):
        try:
            pack = task_pack_for(pack_name)
        except NotImplementedError:
            continue
        active_rows = session.exec(
            select(PromptVersion).where(
                PromptVersion.pack == pack_name,
                PromptVersion.active.is_(True),  # type: ignore[union-attr]
            )
        ).all()
        for row in active_rows:
            if row.task_name not in pack.tasks:
                row.active = False
                session.add(row)
        for task in pack.tasks.values():
            repo, branch, path = _provenance(pack_name, task.name)
            active = session.exec(
                select(PromptVersion).where(
                    PromptVersion.pack == pack_name,
                    PromptVersion.task_name == task.name,
                    PromptVersion.active.is_(True),  # type: ignore[union-attr]
                )
            ).first()
            if active and (
                active.system_prompt == task.system_prompt
                and active.instruction_template == task.instruction
            ):
                active.source_repo = repo
                active.source_branch = branch
                active.source_path = path
                session.add(active)
                continue
            latest = session.exec(
                select(PromptVersion.version)
                .where(
                    PromptVersion.pack == pack_name,
                    PromptVersion.task_name == task.name,
                )
                .order_by(PromptVersion.version.desc())
            ).first()
            if active:
                active.source_repo = repo
                active.source_branch = branch
                active.source_path = path
                active.active = False
                session.add(active)
            session.add(
                PromptVersion(
                    pack=pack_name,
                    task_name=task.name,
                    version=(latest or 0) + 1,
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

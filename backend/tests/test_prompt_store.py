import importlib.util
from pathlib import Path

from app.models import PromptVersion
from app.prompts.store import resolve_prompt
from app.tasks.base import Task, TaskPack
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine

_SEED_SPEC = importlib.util.spec_from_file_location(
    "seed_prompts", Path(__file__).parents[2] / "scripts" / "seed_prompts.py"
)
assert _SEED_SPEC and _SEED_SPEC.loader
seed_module = importlib.util.module_from_spec(_SEED_SPEC)
_SEED_SPEC.loader.exec_module(seed_module)


class Output(BaseModel):
    ok: bool


def test_prompt_resolution_override_then_db_then_code() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    task = Task("task", "code-system", "code-instruction", Output)
    with Session(engine) as session:
        assert resolve_prompt(session, "OPD", task).source == "code"
        session.add(
            PromptVersion(
                pack="OPD",
                task_name="task",
                version=1,
                system_prompt="db-system",
                instruction_template="db-instruction",
            )
        )
        session.commit()
        db = resolve_prompt(session, "OPD", task)
        assert (db.system_prompt, db.instruction_template, db.source) == (
            "db-system",
            "db-instruction",
            "db:v1",
        )
        override = resolve_prompt(
            session,
            "OPD",
            task,
            {"system_prompt": "override-system"},
        )
        assert (override.system_prompt, override.instruction_template, override.source) == (
            "override-system",
            "db-instruction",
            "override",
        )


def test_seed_prompts_is_idempotent(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    task = Task("task", "system", "instruction", Output)
    pack = TaskPack("OPD", {"task": task}, ["task"])
    monkeypatch.setattr(
        seed_module,
        "task_pack_for",
        lambda name: pack if name == "OPD" else (_ for _ in ()).throw(NotImplementedError),
    )
    with Session(engine) as session:
        assert seed_module.seed_prompts(session) == 1
        session.commit()
        assert seed_module.seed_prompts(session) == 0

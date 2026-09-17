import importlib.util
from pathlib import Path

from app.models import PromptVersion
from app.tasks.opd import OPD_TASKS
from app.tasks.prompts.opd_minimal import MINIMAL_OPD_PROMPTS
from sqlmodel import Session, SQLModel, create_engine, select

_SPEC = importlib.util.spec_from_file_location(
    "seed_minimal_opd_prompts",
    Path(__file__).parents[2] / "scripts" / "seed_minimal_opd_prompts.py",
)
assert _SPEC and _SPEC.loader
seed_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed_module)


def test_minimal_opd_prompts_are_complete_shorter_and_seed_once() -> None:
    model_tasks = {name for name, task in OPD_TASKS.items() if not task.deterministic}
    assert MINIMAL_OPD_PROMPTS.keys() == model_tasks
    assert all(
        len(system) < len(OPD_TASKS[name].system_prompt)
        for name, (system, _) in MINIMAL_OPD_PROMPTS.items()
    )
    assert all("{{JSON_OUTPUT}}" not in system for system, _ in MINIMAL_OPD_PROMPTS.values())
    assert "{{JSON_OUTPUT}}" in MINIMAL_OPD_PROMPTS["audit"][1]

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        assert seed_module.seed_minimal_opd_prompts(session) == len(model_tasks)
        session.commit()
        assert seed_module.seed_minimal_opd_prompts(session) == 0
        rows = session.exec(select(PromptVersion)).all()
        assert len(rows) == len(model_tasks)
        assert all(not row.active and row.source_branch == "updates-minimal" for row in rows)

from app.tasks.base import SubsetError, Task, TaskPack
from pydantic import BaseModel


class Output(BaseModel):
    ok: bool


def test_subset_layers_gold_requirements_and_model_validation() -> None:
    segregation = Task("segregation", "", "", Output)
    audit = Task(
        "audit",
        "",
        "",
        Output,
        depends_on=("segregation", "nme_analysis"),
        gold_feed_keys=("nme_analysis", "upstream_bills"),
    )
    pack = TaskPack("OPD", {"segregation": segregation, "audit": audit}, ["segregation", "audit"])

    plan = pack.resolve_subset(["segregation", "audit"], "gold")
    assert plan.layers == [["segregation"], ["audit"]]
    assert plan.gold_requirements == {"audit": ("upstream_bills",)}

    try:
        pack.resolve_subset(["audit"], "model")
    except SubsetError as exc:
        assert "nme_analysis" in str(exc) and "segregation" in str(exc)
    else:
        raise AssertionError("model mode accepted missing dependencies")

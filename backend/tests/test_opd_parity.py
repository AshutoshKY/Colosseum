from app.tasks.claim_types import get_task_pack


def test_opd_parity_tasks_and_reference_runtime() -> None:
    pack = get_task_pack("OPD")
    expected = {
        "claim_form",
        "prescription",
        "identity_document",
        "cheque_bank",
        "extract_icd_codes",
        "patient_summary",
        "merge_bills",
    }
    assert expected <= pack.tasks.keys()
    assert pack.tasks["segregation"].reference_runtime.thinking_level == "low"
    assert pack.tasks["itemized_bills"].reference_runtime.thinking_budget == 8000
    assert pack.tasks["audit"].reference_runtime.max_output_tokens == 16000


def test_opd_seg_audit_gold_requirements_exclude_selected_segmentation() -> None:
    plan = get_task_pack("OPD").resolve_subset(["segregation", "audit"], "gold")
    assert plan.layers == [["segregation"], ["audit"]]
    assert plan.gold_requirements["audit"] == (
        "nme_analysis",
        "patient_summary",
        "benefit_plan",
        "extract_icd_codes",
    )

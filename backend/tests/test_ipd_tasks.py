from app.tasks.claim_types import get_task_pack


def test_ipd_pack_dependencies_runtimes_and_subset_gold() -> None:
    pack = get_task_pack("IPD")
    assert len(pack.tasks) == 13
    assert pack.tasks["audit"].reference_runtime.model_id == "gemini-3.1-pro"
    assert pack.tasks["audit"].reference_runtime.thinking_level == "medium"
    assert pack.tasks["audit"].reference_runtime.max_output_tokens == 16000
    plan = pack.resolve_subset(["segregation", "audit"], "gold")
    assert plan.layers == [["segregation"], ["audit"]]
    assert plan.gold_requirements == {"audit": ("nme_analysis", "patient_summary")}


def test_pp_variant_drops_consolidated_and_merges_itemized_only() -> None:
    pack = get_task_pack("IPD", "PP")
    assert "consolidated_bills" not in pack.tasks
    merge = pack.tasks["merge_bills"]
    assert merge.depends_on == ("itemized_bills",)
    output = merge.run_transform(
        {"itemized_bills": {"bills": [{"bill": {"invoice_number": "I1"}, "items": []}]}}
    )
    assert output["bills"][0]["bill"]["bill_id"] == "I1"


def test_ipd_deterministic_patient_summary_and_validation() -> None:
    pack = get_task_pack("IPD")
    summary = pack.tasks["patient_summary"].run_transform(
        {
            "claim_form": {"part_a": {"patient_name": "A"}, "part_b": {"hospital": "H"}},
            "discharge_summary": {"claims_digitization_details": {"diagnosis": "D"}},
            "cheque_bank": {},
            "identity_document": {},
        }
    )
    assert summary["patient_details"]["patient_name"] == "A"
    validation = pack.tasks["validation"].run_transform(
        {
            "nme_analysis": {
                "nme_list": [{"nme_item": {"bill_amount": 100, "admissible_amount": 80}}]
            },
            "patient_summary": summary,
            "segregation": {},
        }
    )
    assert validation == {
        "bill_total": 100.0,
        "admissible_total": 80.0,
        "patient_summary_complete": True,
    }

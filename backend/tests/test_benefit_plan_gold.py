from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

from app.tasks.schemas.opd_superclaims_ekincare import BenefitPlanSelectionOutput

REPO_ROOT = Path(__file__).parents[2]


def _identity(item: dict) -> tuple[str, int]:
    return str(item["bill_id"]), int(item.get("s.no.", item.get("s_no")))


def test_all_benefit_plan_gold_matches_its_input_catalog_and_bill_items() -> None:
    checked = 0
    for path in sorted((REPO_ROOT / "data" / "gold").glob("*.json")):
        tasks = json.loads(path.read_text())["tasks"]
        if "benefit_plan" not in tasks:
            continue
        checked += 1
        gold = BenefitPlanSelectionOutput.model_validate(tasks["benefit_plan"]).model_dump()
        plans = gold["plan_applicability"]
        assignments = gold["item_assignments"]
        catalog = (tasks["upstream_benefits"] or {}).get("benefits", [])
        bill_items = [
            {
                **item,
                "bill_id": (entry.get("bill") or {}).get("bill_id")
                or (entry.get("bill") or {}).get("invoice_number"),
            }
            for entry in tasks["upstream_bills"]["bills"]
            for item in entry.get("items", [])
        ]

        assert [(p["benefit_id"], p["benefit_name"]) for p in plans] == [
            (p.get("benefit_id"), p.get("benefit_name")) for p in catalog
        ], path.name
        assert Counter(_identity(item) for item in bill_items) == Counter(
            (str(item["bill_id"]), int(item["item_s_no"])) for item in assignments
        ), path.name
        applicable = {
            (plan["benefit_id"], plan["benefit_name"])
            for plan in plans
            if plan["applicable"]
        }
        assert all(
            assignment["benefit_id"] is None
            or (assignment["benefit_id"], assignment["benefit_name"]) in applicable
            for assignment in assignments
        ), path.name
    assert checked >= 14


def test_converter_uses_reviewed_status_bill_items_and_canonical_serial_number() -> None:
    spec = importlib.util.spec_from_file_location(
        "convert_gold_exports", REPO_ROOT / "scripts" / "convert_gold_exports.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upstream = {
        "bills": [
            {
                "bill": {"bill_id": "B1", "invoice_number": "INV1"},
                "items": [{"item_id": "1", "s.no.": 3}],
            }
        ]
    }
    edited = {
        "benefit_plan_breakdown": [
            {
                "benefit_id": 1,
                "benefit_name": "Dental",
                "status": "NOT_APPLICABLE",
                "reason": "No dental service",
                "bill_items": [],
            },
            {
                "benefit_id": 2,
                "benefit_name": "Consultation",
                "status": "APPROVED",
                "applicability_reason": "Consultation supplied",
                "bill_items": [{"bill_id": "B1", "item_id": "1", "s.no.": 1}],
            },
        ]
    }

    gold = module._gold_benefit_plan({}, edited, upstream)

    assert [plan["applicable"] for plan in gold["plan_applicability"]] == [False, True]
    assert gold["item_assignments"] == [
        {
            "bill_id": "B1",
            "item_s_no": 3,
            "benefit_id": 2,
            "benefit_name": "Consultation",
        }
    ]

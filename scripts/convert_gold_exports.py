"""Convert healthpay-ai DB export CSVs (from scripts/export_gold_*.sql) into Colosseum
ground-truth gold JSON (docs/ground-truth-format.md), one file per claim.

Sources per task (human-corrected data preferred):
  segregation          <- row.segments (production document_segments)
  itemized_bills       <- extracted.pharmacy_bills (pruned to the ItemizedBillsOutput schema)
  items_categorisation <- extracted.nme_analysis bills (bill_id + s.no. + category)
  nme_analysis         <- latest review edited_payload.nme_analysis (is_nme items), falling back
                          to extracted.nme_analysis
  audit                <- latest review edited_payload.audit_analysis (flat, human-reviewed),
                          falling back to extracted.audit_analysis (nested 'analysis' flattened);
                          pruned to the AuditAnalysisOutput schema
  policy_extraction    <- row.policy_extraction (numbered strings split into lists)

Plus one NON-scored context entry per document:
  upstream_bills       <- extracted.nme_analysis bills verbatim (merged categorised bills with
                          bill_id + s.no. + category) so dependent tasks (items_categorisation,
                          nme, benefit_plan, audit) can be fed golden upstream data instead of
                          another model's live output.

Usage:
    uv run python scripts/convert_gold_exports.py data/gold_exports/*.csv --out data/gold/
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

# Export rows carry a single multi-KB ``json_build_object`` cell that blows past csv's
# default 131072-byte per-field cap; lift it well above any realistic claim payload.
csv.field_size_limit(256 * 1024 * 1024)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DOCS = REPO_ROOT / "test-docs"
# Directories searched for a stem's PDF, in priority order. Uploaded claims land in
# ``data/uploads``; the committed fixtures live in ``test-docs``.
DOC_DIRS = (TEST_DOCS, REPO_ROOT / "data" / "uploads")

# Schema field allowlists (keep gold comparable to what models emit).
BILL_HEADER_FIELDS = {
    "invoice_number", "ip_number", "bill_date", "total_discount", "net_amount",
    "page_number", "facility_details",
}
FACILITY_FIELDS = {"name", "registration_number"}
BILL_ITEM_FIELDS = {
    "item_name", "brand_name", "generic_name", "unit_price", "quantity", "discount",
    "final_amount", "net_amount", "is_returned",
}
AUDIT_FIELDS = {
    "original_claimed_amount", "original_total_of_bills", "updated_claimed_amount",
    "true_total_of_bills", "discrepancy_amount", "status", "discrepancy_reason",
    "bills_analyzed", "duplicates_found", "bills_with_corrections", "patches_applied",
    "medical_legibility_issues", "policy_violations_count", "policy_remarks",
    "medical_legibility", "policy_violations", "icd_codes", "fwa_flags", "patches", "warnings",
}
ICD_FIELDS = {"code", "name", "diagnosis", "description", "chapter", "block", "source", "type"}
VIOLATION_FIELDS = {
    "rule_name", "item_name", "bill_id", "item_s_no", "violation_details",
    "amount_impacted", "recommendation",
}
PATCH_FIELDS = {
    "type", "bill_id", "item_s_no", "reason", "page_reference", "impact",
    "bill_invoice_number", "bill_net_amount", "key", "old_value", "new_value",
    "calculation", "new_amount", "old_amount", "flag_type", "recommendation",
}
LEGIBILITY_FIELDS = {
    "prescription_bill_match", "diagnosis_treatment_consistent", "flagged_items", "summary",
}
FLAGGED_ITEM_FIELDS = {"item_name", "bill_id", "flag_reason", "recommendation"}


def _drop_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_nulls(v) for v in obj]
    return obj


def _prune(d: dict[str, Any] | None, fields: set[str]) -> dict[str, Any]:
    return {k: v for k, v in (d or {}).items() if k in fields}


def _item_sno(item: dict[str, Any]) -> int | None:
    sno = item.get("s.no.", item.get("s_no", item.get("serial_no")))
    try:
        return int(sno) if sno is not None else None
    except (TypeError, ValueError):
        return None


def _find_pdf(stem: str) -> str:
    base_stem = stem.rsplit("_", 1)[0] if "_" in stem else stem
    for base in DOC_DIRS:
        for candidate in (
            f"{stem}.pdf",
            f"{stem}_1.pdf",
            f"{stem}-1.pdf",
            f"{base_stem}.pdf",
            f"{base_stem}_1.pdf",
            f"{base_stem}-1.pdf",
        ):
            if (base / candidate).is_file():
                return (base / candidate).relative_to(REPO_ROOT).as_posix()
    for base in DOC_DIRS:
        hits = sorted(base.glob(f"{base_stem}*.pdf"))
        if hits:
            return hits[0].relative_to(REPO_ROOT).as_posix()
    return f"data/uploads/{stem}.pdf"


def _gold_segregation(row: dict[str, Any]) -> dict[str, Any] | None:
    segs = row.get("segments") or []
    if not segs and isinstance(row.get("extracted"), dict):
        segs = row.get("extracted", {}).get("segregation", {}).get("segments", [])
    if not segs:
        return None
    out_segs = []
    for s in segs:
        if not isinstance(s, dict):
            continue
        dtype = s.get("document_type") or s.get("segment_type")
        prange = s.get("pages") or s.get("page_range")
        if dtype and prange:
            out_segs.append({"document_type": dtype, "pages": str(prange)})
    return {"segments": out_segs} if out_segs else None



def _gold_itemized_bills(pharmacy: dict[str, Any] | None) -> dict[str, Any] | None:
    bills = (pharmacy or {}).get("bills") or []
    if not bills:
        return None
    out = []
    for entry in bills:
        header = _prune(entry.get("bill"), BILL_HEADER_FIELDS)
        if "facility_details" in header:
            header["facility_details"] = _prune(header["facility_details"], FACILITY_FIELDS)
        items = [_prune(it, BILL_ITEM_FIELDS) for it in entry.get("items") or []]
        out.append({"bill": header, "items": items})
    return _drop_nulls({"bills": out})


def _gold_items_categorisation(nme_extracted: dict[str, Any] | None) -> dict[str, Any] | None:
    bills = (nme_extracted or {}).get("bills") or []
    groups = []
    for entry in bills:
        bill_id = (entry.get("bill") or {}).get("bill_id")
        cat_items = [
            {"s.no.": _item_sno(it), "category": it.get("category")}
            for it in entry.get("items") or []
            if it.get("category") and _item_sno(it) is not None
        ]
        if bill_id and cat_items:
            groups.append({"bill_id": bill_id, "categorized_items": cat_items})
    return {"bill_item_categories": groups} if groups else None


def _gold_nme(edited_nme: dict[str, Any] | None, extracted_nme: dict[str, Any] | None) -> dict[str, Any] | None:
    source = edited_nme if (edited_nme or {}).get("bills") else extracted_nme
    bills = (source or {}).get("bills") or []
    if not bills:
        return None
    nme_list = []
    for entry in bills:
        for it in entry.get("items") or []:
            if not it.get("is_nme"):
                continue
            sno = _item_sno(it)
            nme_list.append(
                {
                    "nme_item": _drop_nulls(
                        {
                            "sr.no": sno,
                            "item_name": it.get("nme_item_name") or it.get("item_name"),
                            "bill_amount": it.get("nme_bill_amount") or it.get("final_amount"),
                            "deduction_reason": it.get("deduction_reason") or "",
                        }
                    )
                }
            )
    return {"nme_list": nme_list}  # empty list is valid gold: "no NME items"


def _flatten_extracted_audit(audit: dict[str, Any]) -> dict[str, Any]:
    """Extracted audit_analysis nests the numbers under 'analysis' and booleans under
    'validation'; the review payload (and our schema) is flat."""
    flat = dict(audit.get("analysis") or {})
    for key in ("patches", "icd_codes", "policy_violations", "medical_legibility", "fwa_flags"):
        if key in audit:
            flat[key] = audit[key]
    validation = audit.get("validation") or {}
    flat.update({k: v for k, v in validation.items() if k != "warnings"})
    if validation.get("warnings"):
        flat["warnings"] = validation["warnings"]
    return flat


def _gold_audit(edited_audit: dict[str, Any] | None, extracted_audit: dict[str, Any] | None) -> dict[str, Any] | None:
    source = edited_audit or ( _flatten_extracted_audit(extracted_audit) if extracted_audit else None)
    if not source:
        return None
    if "analysis" in source:  # some review payloads may still carry the nested form
        source = _flatten_extracted_audit(source)
    gold = _prune(source, AUDIT_FIELDS)
    gold["icd_codes"] = [_prune(c, ICD_FIELDS) for c in source.get("icd_codes") or []]
    gold["policy_violations"] = [_prune(v, VIOLATION_FIELDS) for v in source.get("policy_violations") or []]
    gold["patches"] = [_prune(p, PATCH_FIELDS) for p in source.get("patches") or []]
    leg = _prune(source.get("medical_legibility") or {}, LEGIBILITY_FIELDS)
    if leg.get("flagged_items"):
        leg["flagged_items"] = [_prune(f, FLAGGED_ITEM_FIELDS) for f in leg["flagged_items"]]
    gold["medical_legibility"] = leg
    return _drop_nulls(gold)


def _split_numbered(text: str | None) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        head, _, rest = line.partition(". ")
        out.append(rest.strip() if head.rstrip(".").isdigit() and rest else line)
    return out


def _gold_policy(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("policy_extraction")
    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    return {
        "nme_items": _split_numbered(payload.get("nme_items")),
        "policy_rules": _split_numbered(payload.get("policy_rules")),
        "extraction_ok": bool(payload.get("extraction_ok", True)),
    }


def _gold_benefits(edited: dict[str, Any]) -> dict[str, Any] | None:
    """Benefit-plan catalog for this claim (from the production breakdown) — upstream context
    for the benefit_plan task, NOT scored gold."""
    breakdown = (edited or {}).get("benefit_plan_breakdown") or []
    benefits = [
        _drop_nulls(
            {
                "benefit_id": b.get("benefit_id"),
                "benefit_name": b.get("benefit_name"),
                "required_documents": b.get("required_documents"),
            }
        )
        for b in breakdown
        if b.get("benefit_id") or b.get("benefit_name")
    ]
    return {"benefits": benefits} if benefits else None


def _gold_cheque_bank(
    extracted_map: dict[str, Any], edited: dict[str, Any], doc_details: dict[str, Any]
) -> dict[str, Any] | None:
    raw = (
        extracted_map.get("cheque_or_bank_details")
        or extracted_map.get("cheque_bank")
        or edited.get("bank_details")
        or doc_details.get("bank_details")
    )
    if not raw:
        return None
    if isinstance(raw, dict) and "bank_details" in raw:
        details = raw.get("bank_details")
    elif isinstance(raw, dict):
        details = raw
    else:
        return None
    if not details or not isinstance(details, dict):
        return {"bank_details": None}
    bank_fields = {"ifsc_code", "bank_name", "bank_branch", "account_no", "account_holder_name", "account_type"}
    pruned = _prune(details, bank_fields)
    return {"bank_details": pruned if any(v is not None for v in pruned.values()) else None}


def _gold_prescription(
    extracted_map: dict[str, Any], edited: dict[str, Any]
) -> dict[str, Any] | None:
    raw = extracted_map.get("prescription") or edited.get("prescription")
    if not raw or not isinstance(raw, dict):
        return None
    if "claims_digitization_details" in raw:
        return _drop_nulls(raw)
    return _drop_nulls({"claims_digitization_details": raw})


def _gold_icd_codes(
    extracted_map: dict[str, Any], edited: dict[str, Any]
) -> dict[str, Any] | None:
    raw = (
        extracted_map.get("icd_codes")
        or extracted_map.get("extract_icd_codes")
        or edited.get("icd_codes")
        or (edited.get("audit_analysis") or {}).get("icd_codes")
    )
    if raw is None:
        return None
    codes = raw.get("icd_codes", raw) if isinstance(raw, dict) else raw
    if not isinstance(codes, list):
        return None
    return _drop_nulls({"icd_codes": [_prune(c, ICD_FIELDS | {"related_bill_ids"}) for c in codes if isinstance(c, dict)]})


def _gold_patient_summary(
    extracted_map: dict[str, Any], edited: dict[str, Any]
) -> dict[str, Any] | None:
    raw = extracted_map.get("patient_summary") or edited.get("patient_summary")
    if not raw or not isinstance(raw, dict):
        return None
    if "patient_summary" in raw:
        return _drop_nulls(raw)
    return _drop_nulls({"patient_summary": raw})


def _gold_benefit_plan(
    extracted_map: dict[str, Any], edited: dict[str, Any]
) -> dict[str, Any] | None:
    raw = (
        extracted_map.get("benefit_plan")
        or extracted_map.get("benefit_plan_selection")
        or edited.get("benefit_plan_selection")
    )
    if isinstance(raw, dict) and "plan_applicability" in raw:
        return _drop_nulls(raw)
    # If we have edited benefit_plan_breakdown, map it to BenefitPlanSelectionOutput shape
    breakdown = edited.get("benefit_plan_breakdown")
    if isinstance(breakdown, list) and breakdown:
        plans = []
        items = []
        for b in breakdown:
            if not isinstance(b, dict):
                continue
            plans.append(
                {
                    "benefit_id": b.get("benefit_id"),
                    "benefit_name": b.get("benefit_name") or "",
                    "applicable": bool(b.get("applicable", True)),
                    "confidence": 1.0,
                    "reason": b.get("reason"),
                }
            )
            for it in b.get("items") or b.get("assigned_items") or []:
                if isinstance(it, dict):
                    items.append(
                        {
                            "bill_id": it.get("bill_id"),
                            "item_s_no": it.get("item_s_no") or it.get("s_no") or it.get("s.no."),
                            "benefit_id": b.get("benefit_id"),
                            "benefit_name": b.get("benefit_name"),
                        }
                    )
        if plans:
            return _drop_nulls({"plan_applicability": plans, "item_assignments": items})
    return None


def _gold_claim_form(extracted_map: dict[str, Any], edited: dict[str, Any]) -> dict[str, Any] | None:
    raw = extracted_map.get("claim_forms") or extracted_map.get("claim_form") or edited.get("claim_forms")
    if isinstance(raw, dict) and raw:
        return _drop_nulls(raw)
    return None


def _gold_identity_document(extracted_map: dict[str, Any], edited: dict[str, Any]) -> dict[str, Any] | None:
    raw = extracted_map.get("identity_documents") or extracted_map.get("identity_document") or edited.get("identity_documents")
    if isinstance(raw, dict) and raw:
        return _drop_nulls(raw)
    return None


def _extracted_by_type(row: dict[str, Any]) -> dict[str, Any]:
    """Support both Healthpay's history array and Superclaims' keyed JSON object."""
    raw = row.get("extracted") or []
    if isinstance(raw, dict):
        return raw
    out: dict[str, Any] = {}
    for entry in raw:
        if isinstance(entry, dict) and entry.get("document_type"):
            out.setdefault(entry["document_type"], entry.get("json_data"))
    return out


def convert_row(row: dict[str, Any]) -> dict[str, Any] | None:
    stem = row["stem"]
    document = _find_pdf(stem)
    if not document:
        print(f"  ! no test-docs PDF for stem {stem}; skipping", file=sys.stderr)
        return None

    extracted_map = _extracted_by_type(row)
    doc_details = row.get("doc_details") or {}
    if not isinstance(doc_details, dict):
        doc_details = {}

    reviews = row.get("review") or []
    latest = reviews[0] if reviews else {}
    edited = latest.get("edited_payload") or latest.get("original_payload") or {}

    tasks: dict[str, Any] = {}
    if (gold := _gold_segregation(row)) is not None:
        tasks["segregation"] = gold
    if (gold := _gold_itemized_bills(extracted_map.get("pharmacy_bills") or edited.get("bill_data"))) is not None:
        tasks["itemized_bills"] = gold
    if (gold := _gold_items_categorisation(extracted_map.get("nme_analysis") or edited.get("nme_analysis"))) is not None:
        tasks["items_categorisation"] = gold
    if (gold := _gold_nme(edited.get("nme_analysis"), extracted_map.get("nme_analysis"))) is not None:
        tasks["nme_analysis"] = gold
    if (gold := _gold_audit(edited.get("audit_analysis"), extracted_map.get("audit_analysis"))) is not None:
        tasks["audit"] = gold
    if (gold := _gold_policy(row)) is not None:
        tasks["policy_extraction"] = gold
    if (gold := _gold_cheque_bank(extracted_map, edited, doc_details)) is not None:
        tasks["cheque_bank"] = gold
    if (gold := _gold_prescription(extracted_map, edited)) is not None:
        tasks["prescription"] = gold
    if (gold := _gold_icd_codes(extracted_map, edited)) is not None:
        tasks["extract_icd_codes"] = gold
    if (gold := _gold_patient_summary(extracted_map, edited)) is not None:
        tasks["patient_summary"] = gold
    if (gold := _gold_benefit_plan(extracted_map, edited)) is not None:
        tasks["benefit_plan"] = gold
    if (gold := _gold_claim_form(extracted_map, edited)) is not None:
        tasks["claim_form"] = gold
    if (gold := _gold_identity_document(extracted_map, edited)) is not None:
        tasks["identity_document"] = gold
    if (payload := extracted_map.get("discharge_summary")):
        tasks["discharge_summary"] = _drop_nulls(payload)
    if (payload := extracted_map.get("validation")):
        tasks["validation"] = _drop_nulls(payload)

    # Context (not scored): merged categorised bills + benefit catalog for feeding dependent tasks.
    upstream = extracted_map.get("nme_analysis") or edited.get("nme_analysis")
    if upstream and upstream.get("bills"):
        tasks["upstream_bills"] = upstream
    if (benefits := _gold_benefits(edited) or _gold_benefits(doc_details)) is not None:
        tasks["upstream_benefits"] = benefits

    if not tasks:
        return None
    return {"document": document, "tasks": tasks}



def load_rows(csv_paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Parse export CSVs; one preferred row per stem (claim_id matching the stem wins)."""
    by_stem: dict[str, dict[str, Any]] = {}
    for path in csv_paths:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                cell = raw.get("json_build_object") or next(iter(raw.values()))
                if not cell:
                    continue
                row = json.loads(cell)
                stem, claim_id = row["stem"], row.get("claim_id") or ""
                is_primary = claim_id.replace("-", "_").startswith(stem.replace("-", "_"))
                current = by_stem.get(stem)
                if current is None or (is_primary and not current["_primary"]):
                    row["_primary"] = is_primary
                    by_stem[stem] = row
    return by_stem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csvs", nargs="+", help="export CSV file(s)")
    parser.add_argument("--out", default="data/gold", help="output directory for gold JSON")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows([Path(p) for p in args.csvs])
    written = 0
    for stem, row in sorted(rows.items()):
        record = convert_row(row)
        if record is None:
            continue
        (out_dir / f"{stem}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written += 1
        print(f"  {stem}: tasks={sorted(record['tasks'])}")
    print(f"wrote {written} gold file(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DOCS = REPO_ROOT / "test-docs"

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


def _find_pdf(stem: str) -> str | None:
    for candidate in (f"{stem}_1.pdf", f"{stem}-1.pdf"):
        if (TEST_DOCS / candidate).is_file():
            return f"test-docs/{candidate}"
    hits = sorted(TEST_DOCS.glob(f"{stem}*.pdf"))
    return f"test-docs/{hits[0].name}" if hits else None


def _gold_segregation(row: dict[str, Any]) -> dict[str, Any] | None:
    segs = row.get("segments") or []
    if not segs:
        return None
    return {
        "segments": [
            {"document_type": s.get("segment_type"), "pages": s.get("page_range")}
            for s in segs
            if s.get("segment_type") and s.get("page_range")
        ]
    }


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


def convert_row(row: dict[str, Any]) -> dict[str, Any] | None:
    stem = row["stem"]
    document = _find_pdf(stem)
    if not document:
        print(f"  ! no test-docs PDF for stem {stem}; skipping", file=sys.stderr)
        return None

    extracted_map: dict[str, Any] = {}
    for entry in row.get("extracted") or []:
        extracted_map.setdefault(entry["document_type"], entry.get("json_data"))

    reviews = row.get("review") or []
    latest = reviews[0] if reviews else {}
    edited = latest.get("edited_payload") or latest.get("original_payload") or {}

    tasks: dict[str, Any] = {}
    if (gold := _gold_segregation(row)) is not None:
        tasks["segregation"] = gold
    if (gold := _gold_itemized_bills(extracted_map.get("pharmacy_bills"))) is not None:
        tasks["itemized_bills"] = gold
    if (gold := _gold_items_categorisation(extracted_map.get("nme_analysis"))) is not None:
        tasks["items_categorisation"] = gold
    if (gold := _gold_nme(edited.get("nme_analysis"), extracted_map.get("nme_analysis"))) is not None:
        tasks["nme_analysis"] = gold
    if (gold := _gold_audit(edited.get("audit_analysis"), extracted_map.get("audit_analysis"))) is not None:
        tasks["audit"] = gold
    if (gold := _gold_policy(row)) is not None:
        tasks["policy_extraction"] = gold

    # Context (not scored): merged categorised bills + benefit catalog for feeding dependent tasks.
    upstream = extracted_map.get("nme_analysis")
    if upstream and upstream.get("bills"):
        tasks["upstream_bills"] = upstream
    if (benefits := _gold_benefits(edited)) is not None:
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

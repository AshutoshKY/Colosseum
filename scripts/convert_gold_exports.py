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


def _format_page_ranges(ranges: Any) -> str | None:
    if isinstance(ranges, str):
        return ranges.strip() if ranges.strip() else None
    if isinstance(ranges, (int, float)):
        return str(int(ranges))
    if not isinstance(ranges, list):
        return None
    parts = []
    for r in ranges:
        if isinstance(r, dict):
            start = r.get("start") or r.get("start_page") or r.get("page")
            end = r.get("end") or r.get("end_page") or start
            if start is not None and end is not None:
                if start == end:
                    parts.append(str(start))
                else:
                    parts.append(f"{start}-{end}")
            elif start is not None:
                parts.append(str(start))
        elif isinstance(r, (int, float)):
            parts.append(str(int(r)))
        elif isinstance(r, str) and r.strip():
            parts.append(r.strip())
    return ", ".join(parts) if parts else None


def _gold_segregation(row: dict[str, Any]) -> dict[str, Any] | None:
    raw_segs = (
        row.get("segments")
        or row.get("segregation")
        or row.get("aggregated_segments")
    )
    if not raw_segs and isinstance(row.get("extracted"), dict):
        raw_segs = row.get("extracted", {}).get("segregation") or row.get("extracted", {}).get("document_segregator")
    if not raw_segs:
        reviews = row.get("review") or []
        latest = reviews[0] if reviews else {}
        edited = latest.get("edited_payload") or latest.get("original_payload") or {}
        raw_segs = (
            edited.get("segments")
            or edited.get("segregation")
            or (edited.get("data") or {}).get("output", {}).get("segregation")
        )

    if isinstance(raw_segs, str):
        try:
            raw_segs = json.loads(raw_segs)
        except json.JSONDecodeError:
            return None

    if not raw_segs:
        return None

    if isinstance(raw_segs, list):
        out_segs = []
        for s in raw_segs:
            if not isinstance(s, dict):
                continue
            dtype = s.get("document_type") or s.get("segment_type")
            prange = s.get("pages") or s.get("page_range") or _format_page_ranges(s.get("page_ranges"))
            if dtype and prange:
                seg_dict: dict[str, Any] = {"document_type": str(dtype), "pages": str(prange)}
                if "is_pharmacy_bill" in s and s["is_pharmacy_bill"] is not None:
                    seg_dict["is_pharmacy_bill"] = bool(s["is_pharmacy_bill"])
                out_segs.append(seg_dict)
        return {"segments": out_segs} if out_segs else None

    if isinstance(raw_segs, dict):
        if "segments" in raw_segs and isinstance(raw_segs["segments"], list):
            return _gold_segregation({"segments": raw_segs["segments"]})

        agg = raw_segs.get("aggregated_segments")
        if not agg or not isinstance(agg, dict):
            agg = raw_segs

        out_segs = []
        for dtype, dinfo in agg.items():
            if isinstance(dinfo, dict):
                pranges = dinfo.get("page_ranges") or []
                if isinstance(pranges, list) and dtype == "itemized_bill":
                    groups: dict[bool | None, list[Any]] = {}
                    for pr in pranges:
                        pb = pr.get("is_pharmacy_bill") if isinstance(pr, dict) else None
                        groups.setdefault(pb, []).append(pr)
                    for pb, sub_pranges in groups.items():
                        pages_str = _format_page_ranges(sub_pranges)
                        if pages_str:
                            seg_dict = {"document_type": str(dtype), "pages": pages_str}
                            if pb is not None:
                                seg_dict["is_pharmacy_bill"] = bool(pb)
                            out_segs.append(seg_dict)
                else:
                    pages_str = (
                        _format_page_ranges(pranges)
                        or _format_page_ranges(dinfo.get("pages"))
                        or _format_page_ranges(dinfo.get("page_range"))
                    )
                    if pages_str:
                        out_segs.append({"document_type": str(dtype), "pages": pages_str})
            elif isinstance(dinfo, list):
                pages_str = _format_page_ranges(dinfo)
                if pages_str:
                    out_segs.append({"document_type": str(dtype), "pages": pages_str})
            elif isinstance(dinfo, (str, int)):
                out_segs.append({"document_type": str(dtype), "pages": str(dinfo)})

        return {"segments": out_segs} if out_segs else None

    return None



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


def _gold_policy(row: dict[str, Any], edited: dict[str, Any] | None = None) -> dict[str, Any] | None:
    raw = (
        (edited or {}).get("policy_extraction")
        or row.get("policy_extraction")
    )
    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    nme_items = payload.get("nme_items") or []
    if isinstance(nme_items, str):
        nme_items = _split_numbered(nme_items)
    elif isinstance(nme_items, list):
        nme_items = [str(x).strip() for x in nme_items if str(x).strip()]
    else:
        nme_items = []

    policy_rules = payload.get("policy_rules") or []
    if isinstance(policy_rules, str):
        policy_rules = _split_numbered(policy_rules)
    elif isinstance(policy_rules, list):
        policy_rules = [str(x).strip() for x in policy_rules if str(x).strip()]
    else:
        policy_rules = []

    return {
        "nme_items": nme_items,
        "policy_rules": policy_rules,
        "extraction_ok": bool(payload.get("extraction_ok", True)),
    }


def _gold_benefits(source: dict[str, Any] | None) -> dict[str, Any] | None:
    """Benefit-plan catalog for this claim (from the production breakdown or doc_details) — upstream context
    for the benefit_plan task, NOT scored gold."""
    if not source or not isinstance(source, dict):
        return None
    client_payload = (
        source.get("original_client_payload")
        if isinstance(source.get("original_client_payload"), dict)
        else {}
    )
    breakdown = (
        client_payload.get("benefits")
        or source.get("benefit_plan_breakdown")
        or source.get("benefits")
        or []
    )
    benefits = [
        _drop_nulls(
            {
                "benefit_id": b.get("benefit_id"),
                "benefit_name": b.get("benefit_name"),
                "required_documents": b.get("required_documents"),
            }
        )
        for b in breakdown
        if isinstance(b, dict) and (b.get("benefit_id") or b.get("benefit_name"))
    ]
    return {"benefits": benefits} if benefits else None


def _policy_context(edited: dict[str, Any], doc_details: dict[str, Any]) -> dict[str, Any] | None:
    client_payload = edited.get("original_client_payload") or {}
    raw = client_payload.get("policy") or doc_details.get("policy_text") or doc_details.get("policy")
    if isinstance(raw, str) and raw.strip():
        return {"text": raw.strip()}
    return raw if isinstance(raw, dict) and raw else None


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


def _canonical_benefit_item(
    item: dict[str, Any], upstream_bills: dict[str, Any] | None
) -> tuple[str | None, int | None]:
    """Map reviewed benefit items back to the exact bill identity sent to the model."""
    candidates = []
    for entry in (upstream_bills or {}).get("bills", []) or []:
        bill = entry.get("bill") or {}
        for upstream_item in entry.get("items", []) or []:
            candidates.append(
                {
                    "bill_id": bill.get("bill_id") or bill.get("invoice_number"),
                    "invoice_number": bill.get("invoice_number"),
                    "item_id": upstream_item.get("item_id"),
                    "item_s_no": _item_sno(upstream_item),
                }
            )

    bill_id = item.get("bill_id")
    invoice = item.get("invoice_number") or item.get("Bill_Number")
    scoped = [
        row
        for row in candidates
        if (bill_id is not None and str(row["bill_id"]) == str(bill_id))
        or (bill_id is None and invoice is not None and str(row["invoice_number"]) == str(invoice))
    ]
    item_id = item.get("item_id")
    by_item_id = [row for row in scoped if item_id is not None and str(row["item_id"]) == str(item_id)]
    if len(by_item_id) == 1:
        scoped = by_item_id
    else:
        raw_s_no = item.get("item_s_no")
        raw_s_no = _item_sno(item) if raw_s_no is None else raw_s_no
        by_s_no = [row for row in scoped if row["item_s_no"] == raw_s_no]
        if len(by_s_no) == 1:
            scoped = by_s_no
    if len(scoped) == 1:
        return str(scoped[0]["bill_id"]), scoped[0]["item_s_no"]
    raw_s_no = item.get("item_s_no")
    return (str(bill_id) if bill_id is not None else None, _item_sno(item) if raw_s_no is None else raw_s_no)


def _gold_benefit_plan(
    extracted_map: dict[str, Any],
    edited: dict[str, Any],
    upstream_bills: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    raw = (
        extracted_map.get("benefit_plan")
        or extracted_map.get("benefit_plan_selection")
        or edited.get("benefit_plan_selection")
    )
    if isinstance(raw, dict) and "plan_applicability" in raw:
        return _drop_nulls(raw)
    # Map the human-reviewed production breakdown to the model's structured output.
    breakdown = edited.get("benefit_plan_breakdown")
    if isinstance(breakdown, list) and breakdown:
        plans = []
        items = []
        for b in breakdown:
            if not isinstance(b, dict):
                continue
            status = str(b.get("status") or "").upper()
            applicable = status != "NOT_APPLICABLE" if status else bool(b.get("applicable", True))
            plans.append(
                {
                    "benefit_id": b.get("benefit_id"),
                    "benefit_name": b.get("benefit_name") or "",
                    "applicable": applicable,
                    "confidence": 1.0,
                    "reason": b.get("applicability_reason") or b.get("reason"),
                }
            )
            candidates = []
            for entry in (upstream_bills or {}).get("bills", []) or []:
                bill = entry.get("bill") or {}
                b_id = bill.get("bill_id") or bill.get("invoice_number")
                for u_item in entry.get("items", []) or []:
                    s_no = _item_sno(u_item)
                    if b_id is not None and s_no is not None:
                        candidates.append((str(b_id), int(s_no)))
            valid_keys = set(candidates)

            reviewed_items = b.get("bill_items") or b.get("items") or b.get("assigned_items") or []
            for it in reviewed_items if applicable else []:
                if isinstance(it, dict):
                    bill_id, item_s_no = _canonical_benefit_item(it, upstream_bills)
                    if (str(bill_id), int(item_s_no) if item_s_no is not None else -1) in valid_keys:
                        items.append(
                            {
                                "bill_id": str(bill_id),
                                "item_s_no": int(item_s_no),
                                "benefit_id": b.get("benefit_id"),
                                "benefit_name": b.get("benefit_name"),
                            }
                        )
        if plans:
            # Ensure every item in upstream_bills is represented in item_assignments
            assigned_keys = {
                (str(it["bill_id"]), int(it["item_s_no"]))
                for it in items
                if it.get("bill_id") is not None and it.get("item_s_no") is not None
            }
            for entry in (upstream_bills or {}).get("bills", []) or []:
                bill = entry.get("bill") or {}
                b_id = bill.get("bill_id") or bill.get("invoice_number")
                for u_item in entry.get("items", []) or []:
                    s_no = _item_sno(u_item)
                    if b_id is not None and s_no is not None and (str(b_id), int(s_no)) not in assigned_keys:
                        items.append(
                            {
                                "bill_id": str(b_id),
                                "item_s_no": int(s_no),
                                "benefit_id": None,
                                "benefit_name": None,
                            }
                        )
                        assigned_keys.add((str(b_id), int(s_no)))
            return {"plan_applicability": _drop_nulls(plans), "item_assignments": items}
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
    raw_edited = latest.get("edited_payload") or latest.get("original_payload") or {}
    output_payload = (
        (raw_edited.get("data") or {}).get("output")
        if isinstance(raw_edited.get("data"), dict)
        else {}
    )
    if not isinstance(output_payload, dict):
        output_payload = {}
    edited = {**raw_edited, **output_payload}
    if "original_client_payload" in raw_edited and isinstance(raw_edited["original_client_payload"], dict):
        edited["original_client_payload"] = raw_edited["original_client_payload"]

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
    if (gold := _gold_policy(row, edited)) is not None:
        tasks["policy_extraction"] = gold
    if (gold := _gold_cheque_bank(extracted_map, edited, doc_details)) is not None:
        tasks["cheque_bank"] = gold
    if (gold := _gold_prescription(extracted_map, edited)) is not None:
        tasks["prescription"] = gold
    if (gold := _gold_icd_codes(extracted_map, edited)) is not None:
        tasks["extract_icd_codes"] = gold
    if (gold := _gold_patient_summary(extracted_map, edited)) is not None:
        tasks["patient_summary"] = gold
    upstream = extracted_map.get("nme_analysis") or edited.get("nme_analysis")
    if (gold := _gold_benefit_plan(extracted_map, edited, upstream)) is not None:
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
    if upstream and upstream.get("bills"):
        tasks["upstream_bills"] = upstream
    if (benefits := _gold_benefits(edited) or _gold_benefits(doc_details)) is not None:
        tasks["upstream_benefits"] = benefits
    if (policy := _policy_context(edited, doc_details)) is not None:
        tasks["policy"] = policy

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

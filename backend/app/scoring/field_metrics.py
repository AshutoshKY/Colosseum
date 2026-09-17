"""Deterministic field metrics: schema-aware diff of parsed output vs gold JSON.

Computes per-field exact/normalized match, list precision/recall (e.g. bill line items), and a
numeric tolerance for amounts, then an overall field-accuracy. When no ground truth exists, the
scoreboard falls back to structural validity + cost + latency (see ``scoreboard.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUMERIC_TOLERANCE = 0.01  # 1% relative, like the audit decimal tolerance
_MAX_MISMATCH_DETAILS = 80  # bound the stored mismatch examples per result
_SELECTOR_RE = re.compile(r"\[[^\]]*\]")


@dataclass
class FieldMetrics:
    matched: int = 0
    total: int = 0
    numeric_within_tolerance: int = 0
    list_precision: float | None = None
    list_recall: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return (self.matched / self.total) if self.total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 4),
            "matched": self.matched,
            "total": self.total,
            "numeric_within_tolerance": self.numeric_within_tolerance,
            "list_precision": self.list_precision,
            "list_recall": self.list_recall,
            "details": self.details,
        }


def _norm_scalar(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip().lower()
    return v


def _numbers_match(a: float, b: float) -> bool:
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom <= _NUMERIC_TOLERANCE


def score_against_gold(predicted: dict[str, Any] | None, gold: dict[str, Any]) -> FieldMetrics:
    """Recursively compare ``predicted`` against ``gold`` (gold drives the field set)."""
    m = FieldMetrics()
    if predicted is None:
        # Count gold leaves as misses so a null prediction scores 0, not undefined.
        m.total = max(1, _count_leaves(gold))
        return m
    _walk(predicted, gold, m, path="")
    return m


def _count_leaves(node: Any) -> int:
    if isinstance(node, dict):
        return sum(_count_leaves(v) for v in node.values()) or len(node)
    if isinstance(node, list):
        return sum(_count_leaves(v) for v in node) or len(node)
    return 1


def _walk(pred: Any, gold: Any, m: FieldMetrics, *, path: str) -> None:
    if isinstance(gold, dict):
        for key, gval in gold.items():
            pval = pred.get(key) if isinstance(pred, dict) else None
            _walk(pval, gval, m, path=f"{path}.{key}" if path else key)
        return

    if isinstance(gold, list):
        _score_list(pred if isinstance(pred, list) else [], gold, m, path=path)
        return

    # scalar leaf
    m.total += 1
    if isinstance(gold, (int, float)) and isinstance(pred, (int, float)) and not isinstance(gold, bool):
        ok = _numbers_match(float(pred), float(gold))
        m.numeric_within_tolerance += int(ok)
    else:
        ok = _norm_scalar(pred) == _norm_scalar(gold)
    m.matched += int(ok)
    _record_field(m, path, ok)
    if not ok:
        mismatches = m.details.setdefault("mismatches", [])
        if len(mismatches) < _MAX_MISMATCH_DETAILS:
            mismatches.append({"path": path, "pred": pred, "gold": gold})


def _norm_path(path: str) -> str:
    """Collapse list-item selectors so the same field aggregates across items/documents,
    e.g. ``bills[item_name=x].items[s.no.=3].discount`` -> ``bills[].items[].discount``."""
    return _SELECTOR_RE.sub("[]", path)


def _record_field(m: FieldMetrics, path: str, ok: bool) -> None:
    """Per-field match counters (details['fields']) so every output parameter — invoice
    details, item amounts, discounts, ICD codes, ... — can be audited individually."""
    counts = m.details.setdefault("fields", {}).setdefault(_norm_path(path), {"matched": 0, "total": 0})
    counts["total"] += 1
    counts["matched"] += int(ok)


def _list_key(item: Any) -> str:
    """A stable key for set-based list precision/recall (uses the most identifying scalar fields)."""
    if isinstance(item, dict):
        if item.get("bill_id") is not None and item.get("item_s_no") is not None:
            return f"bill_id={_norm_scalar(item['bill_id'])};item_s_no={_norm_scalar(item['item_s_no'])}"
        if item.get("benefit_id") is not None:
            return f"benefit_id={_norm_scalar(item['benefit_id'])}"
        for k in ("item_name", "description", "code", "rule_name", "document_type", "name", "s.no."):
            if k in item and item[k] is not None:
                return f"{k}={_norm_scalar(item[k])}"
        # Bill groups ({"bill": {...}, "items": [...]}): identify by the bill header.
        inner = item.get("bill") or item.get("nme_item")
        if isinstance(inner, dict):
            for k in ("invoice_number", "bill_id", "sr.no", "item_name"):
                if inner.get(k) is not None:
                    return f"{k}={_norm_scalar(inner[k])}"
        return str(sorted((k, _norm_scalar(v)) for k, v in item.items() if not isinstance(v, (dict, list))))
    return str(_norm_scalar(item))


def _score_list(pred: list, gold: list, m: FieldMetrics, *, path: str) -> None:
    gold_keys = [_list_key(x) for x in gold]
    pred_keys = [_list_key(x) for x in pred]
    gold_set, pred_set = set(gold_keys), set(pred_keys)
    tp = len(gold_set & pred_set)
    precision = tp / len(pred_set) if pred_set else (1.0 if not gold_set else 0.0)
    recall = tp / len(gold_set) if gold_set else 1.0
    # Aggregate list P/R (last list wins on the summary fields; details keep per-path).
    m.list_precision = precision
    m.list_recall = recall
    m.details.setdefault("lists", {})[path or "<root>"] = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "tp": tp,
        "pred": len(pred_set),
        "gold": len(gold_set),
    }

    # Dict items: align by identifying key and walk INTO each matched item so every field
    # (amounts, discounts, invoice details, codes, ...) is compared and recorded per-path.
    if gold and all(isinstance(x, dict) for x in gold):
        pred_by_key = {}
        for x in pred:
            if isinstance(x, dict):
                pred_by_key.setdefault(_list_key(x), x)
        for key, gitem in zip(gold_keys, gold, strict=True):
            pitem = pred_by_key.get(key)
            safe_key = key.replace("[", "(").replace("]", ")")
            if pitem is not None:
                _walk(pitem, gitem, m, path=f"{path}[{safe_key}]")
            else:
                # Missing gold item: all its leaves are misses.
                misses = _count_leaves(gitem)
                m.total += misses
                _record_field(m, f"{path}[]", False)
                mismatches = m.details.setdefault("mismatches", [])
                if len(mismatches) < _MAX_MISMATCH_DETAILS:
                    mismatches.append({"path": f"{path}[{key}]", "pred": None, "gold": "<missing item>"})
        return

    # Scalar lists: set membership drives accuracy.
    m.total += len(gold_set) or 1
    m.matched += tp

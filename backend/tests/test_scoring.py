"""Field metrics + scoreboard + ground-truth import tests (offline)."""

from __future__ import annotations

from app.scoring import build_scoreboard, score_against_gold
from app.scoring.scoreboard import ScoreboardRow


def test_field_metrics_exact_and_numeric_tolerance():
    gold = {"status": "OVERCLAIMED", "true_total_of_bills": 1000.0}
    pred = {"status": "overclaimed", "true_total_of_bills": 1005.0}  # within 1% tolerance, case-insensitive
    m = score_against_gold(pred, gold)
    assert m.accuracy == 1.0
    assert m.numeric_within_tolerance == 1


def test_field_metrics_list_precision_recall():
    gold = {"nme_list": [{"item_name": "Registration"}, {"item_name": "Documentation"}]}
    pred = {"nme_list": [{"item_name": "registration"}, {"item_name": "Telephone"}]}
    m = score_against_gold(pred, gold)
    lists = m.details["lists"]["nme_list"]
    assert lists["tp"] == 1
    assert lists["precision"] == 0.5
    assert lists["recall"] == 0.5


def test_null_prediction_scores_zero():
    m = score_against_gold(None, {"a": 1, "b": 2})
    assert m.accuracy == 0.0


def test_scoreboard_ranks_by_composite():
    rows = [
        # cheap+fast+valid should win over expensive+slow
        ScoreboardRow(task="audit", model_id="cheap", valid=True, accuracy=None, total_cost_usd=0.001, latency_ms=500),
        ScoreboardRow(task="audit", model_id="pricey", valid=True, accuracy=None, total_cost_usd=0.05, latency_ms=8000),
        ScoreboardRow(task="audit", model_id="skip", valid=False, accuracy=None, total_cost_usd=0.0, latency_ms=0, skipped=True, skip_reason="not applicable"),
    ]
    build_scoreboard(rows)
    ranked = {r.model_id: r.rank for r in rows if not r.skipped}
    assert ranked["cheap"] == 1
    assert ranked["pricey"] == 2
    # skipped cell is excluded from ranking (recorded "not applicable")
    assert next(r for r in rows if r.model_id == "skip").rank is None


def test_accuracy_beats_cost_when_ground_truth_present():
    rows = [
        ScoreboardRow(task="nme_analysis", model_id="accurate", valid=True, accuracy=1.0, total_cost_usd=0.05, latency_ms=9000),
        ScoreboardRow(task="nme_analysis", model_id="cheap_wrong", valid=True, accuracy=0.2, total_cost_usd=0.001, latency_ms=300),
    ]
    build_scoreboard(rows)
    assert next(r for r in rows if r.model_id == "accurate").rank == 1


def test_ground_truth_import_roundtrip(tmp_path, synthetic_pdf):
    import json

    from app.db import create_all, get_engine, session_scope
    from app.models import GroundTruth
    from app.scoring.ground_truth_import import import_ground_truth
    from sqlmodel import select

    gold_file = tmp_path / "gold.json"
    gold_file.write_text(
        json.dumps(
            {
                "document": synthetic_pdf,
                "tasks": {"segregation": {"segments": [{"document_type": "other", "pages": "1"}]}},
            }
        )
    )
    db_url = f"sqlite:///{tmp_path/'gt.db'}"
    counts = import_ground_truth([str(gold_file)], db_url=db_url)
    assert counts["inserted"] == 1

    engine = get_engine(db_url)
    create_all(engine)
    with session_scope(engine) as session:
        rows = session.exec(select(GroundTruth)).all()
        assert len(rows) == 1
        assert rows[0].task == "segregation"

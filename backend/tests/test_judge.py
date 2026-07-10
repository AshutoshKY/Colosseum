from app.scoring.judge import anonymize_candidates, de_anonymize_ranking
from app.scoring.judge_prompts import gold_grade_instruction
from app.scoring.judge_schemas import CandidateRank, JudgeRankingOutput


def test_grade_modes_coexist_and_aggregate(tmp_path, monkeypatch) -> None:
    import app.scoring.judge as judge_module
    from app.models import BenchmarkRun, DocumentSample, RunCell, RunResult
    from app.scoring.report import judge_aggregates
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'judge.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        document = DocumentSample(path="claim.pdf", sha256="judge-doc")
        run = BenchmarkRun(name="judge")
        session.add(document)
        session.add(run)
        session.flush()
        cell = RunCell(
            run_id=run.id,
            task="audit",
            document_id=document.id,
            model_id="candidate",
        )
        session.add(cell)
        session.flush()
        result = RunResult(cell_id=cell.id, valid=True)
        session.add(result)
        session.commit()
        run_id, result_id = run.id, result.id

    monkeypatch.setattr(judge_module, "get_engine", lambda: engine)
    judge_module._upsert_grade(
        result_id,
        {"mode_used": "gold_grade", "overall_score": 0.8, "field_verdicts": []},
    )
    judge_module._upsert_grade(
        result_id,
        {"mode_used": "doc_grade", "overall_score": 0.6, "field_verdicts": []},
    )
    with Session(engine) as session:
        aggregates = judge_aggregates(session, run_id)
    assert aggregates[("audit", "candidate")]["judge_score"] == 0.7
    assert aggregates[("audit", "candidate")]["judged_cells"] == 2


def test_anonymization_is_reproducible_and_deanonymizes() -> None:
    candidates = {"model-c": {"v": 3}, "model-a": {"v": 1}, "model-b": {"v": 2}}
    first = anonymize_candidates(candidates, run_id=7, document_id=11)
    second = anonymize_candidates(candidates, run_id=7, document_id=11)
    assert first == second
    anonymous, labels, _ = first
    assert set(anonymous) == {"A", "B", "C"}
    output = JudgeRankingOutput(
        ranking=[
            CandidateRank(candidate="Candidate A", rank=1, strengths="accurate", weaknesses="none"),
            CandidateRank(candidate="B", rank=2, strengths="complete", weaknesses="format"),
            CandidateRank(candidate="C", rank=3, strengths="concise", weaknesses="missing"),
        ],
        rationale="Evidence based",
        confidence="high",
    )
    rows = de_anonymize_ranking(output, labels)
    assert [row["model_id"] for row in rows] == [labels["A"], labels["B"], labels["C"]]


def test_judge_prompt_marks_truncation() -> None:
    prompt = gold_grade_instruction("audit", {"large": "x" * 60_000}, {"ok": True})
    assert "truncated at 50,000 characters" in prompt
    assert "CANDIDATE OUTPUT" in prompt

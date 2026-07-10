from app.models import DocumentSample, GroundTruth
from app.runner.upstream import MissingUpstreamData, UpstreamResolver
from sqlmodel import Session, SQLModel, create_engine


def test_upstream_prefers_live_and_accepts_legacy_aliases() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        doc = DocumentSample(path="claim.pdf", sha256="upstream")
        session.add(doc)
        session.flush()
        session.add(GroundTruth(document_id=doc.id, task="upstream_bills", gold={"bills": [1]}))
        session.commit()

        resolver = UpstreamResolver(session, doc, live_outputs={"segregation": {"live": True}})
        assert resolver.get("segregation") == {"live": True}
        assert resolver.get("merge_bills") == {"bills": [1]}
        try:
            resolver.get("missing")
        except MissingUpstreamData as exc:
            assert exc.task == "missing"
        else:
            raise AssertionError("missing upstream data did not raise")

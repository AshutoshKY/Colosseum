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
        session.add(GroundTruth(document_id=doc.id, task="cheque_or_bank_details", gold={"bank_details": {"ifsc_code": "HDFC0001"}}))
        session.add(GroundTruth(document_id=doc.id, task="icd_codes", gold={"icd_codes": [{"code": "J06.9"}]}))
        session.commit()

        resolver = UpstreamResolver(session, doc, live_outputs={"segregation": {"live": True}})
        assert resolver.get("segregation") == {"live": True}
        assert resolver.get("merge_bills") == {"bills": [1]}
        assert resolver.get("cheque_bank") == {"bank_details": {"ifsc_code": "HDFC0001"}}
        assert resolver.get("extract_icd_codes") == {"icd_codes": [{"code": "J06.9"}]}
        try:
            resolver.get("missing")
        except MissingUpstreamData as exc:
            assert exc.task == "missing"
        else:
            raise AssertionError("missing upstream data did not raise")


def test_upstream_dynamic_synthesis() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        doc = DocumentSample(path="claim.pdf", sha256="synth")
        session.add(doc)
        session.flush()
        session.add(
            GroundTruth(
                document_id=doc.id,
                task="itemized_bills",
                gold={"bills": [{"bill": {"invoice_number": "INV-1"}, "items": [{"item_name": "Paracetamol", "final_amount": 50}]}]},
            )
        )
        session.add(
            GroundTruth(
                document_id=doc.id,
                task="prescription",
                gold={"claims_digitization_details": {"diagnosis": "Fever"}},
            )
        )
        session.commit()

        resolver = UpstreamResolver(session, doc)
        # merge_bills dynamically synthesized from itemized_bills
        merged = resolver.get("merge_bills")
        assert "bills" in merged
        assert merged["bills"][0]["bill"]["bill_id"] == "INV-1"

        # patient_summary dynamically synthesized from available components
        ps = resolver.get("patient_summary")
        assert "patient_summary" in ps
        assert ps["patient_summary"]["clinical_details"]["diagnosis"] == "Fever"


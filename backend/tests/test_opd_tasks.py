"""OPD task pack + claim-type layer + rasterizing adapter tests (offline)."""

from __future__ import annotations

import pytest
from app.providers.adapters import CapabilityGateError, DocumentInput, RasterizingAdapter
from app.providers.capabilities import (
    Access,
    Modality,
    ModelCapability,
    Provider,
    StructuredMethod,
)
from app.providers.docprep import base64_size_mb
from app.tasks import OPD_TASKS, merge_bills
from app.tasks.claim_types import get_task_pack, resolve_claim_type


def _grok_like_cap() -> ModelCapability:
    return ModelCapability(
        model_id="vertex_ai/xai/grok-4.20-reasoning",
        display_name="Grok-like",
        provider=Provider.vertex_partner,
        access=Access.maas,
        modalities=frozenset({Modality.text, Modality.image}),
        pdf_native=False,
        vision=True,
        max_image_mb=4.0,
        max_image_megapixels=33.0,
        image_formats=frozenset({"jpeg", "png"}),
        structured_method=StructuredMethod.json_mode,
    )


def _text_only_cap() -> ModelCapability:
    return ModelCapability(
        model_id="vertex_ai/deepseek-ai/deepseek-r1-0528-maas",
        display_name="DeepSeek R1",
        provider=Provider.vertex_partner,
        modalities=frozenset({Modality.text}),
        pdf_native=False,
        vision=False,
        structured_method=StructuredMethod.json_mode,
    )


# ---- OPD task pack ----
def test_opd_pack_has_priority_tasks():
    for name in (
        "segregation",
        "policy_extraction",
        "claim_form",
        "identity_document",
        "prescription",
        "cheque_bank",
        "itemized_bills",
        "consolidated_bills",
        "merge_bills",
        "items_categorisation",
        "nme_analysis",
        "extract_icd_codes",
        "patient_summary",
        "benefit_plan",
        "audit",
    ):
        assert name in OPD_TASKS, name



def test_text_tasks_flagged_and_render():
    nme = OPD_TASKS["nme_analysis"]
    assert nme.is_text_task is True
    rendered = nme.render_instruction(bills_json='{"bills": []}')
    assert '{"bills": []}' in rendered


def test_merge_bills_assigns_serial_numbers():
    merged = merge_bills(
        {"bills": [{"bill": {"invoice_number": "A"}, "items": [{"item_name": "x", "final_amount": 1}, {"item_name": "y", "final_amount": 2}]}]},
        {"bills": [{"bill": {"invoice_number": "B"}, "items": [{"item_name": "z", "final_amount": 3}]}]},
    )
    assert len(merged["bills"]) == 2
    # Consolidated bills come first (mirrors healthpay bill_merger_node), then itemized.
    assert merged["bills"][0]["source"] == "consolidated"
    assert merged["bills"][1]["source"] == "itemized"
    # Per-item 1-based s.no. is assigned, and a bill_id is derived from the invoice number.
    assert merged["bills"][1]["items"][1]["s.no."] == 2
    assert merged["bills"][0]["bill"]["bill_id"] == "B"
    assert merged["bills"][1]["bill"]["bill_id"] == "A"


# ---- Phase 2.5: full healthpay prompts vendored + faithful schemas ----
def test_healthpay_prompts_are_full():
    from app.tasks.prompts import opd_healthpay as p

    # Segregation: the full DOCS_SEGREGATOR framework (all 10 categories + decision tree).
    assert "DocAnalytics-AI" in p.SEGREGATION_PROMPT
    assert "classification_logic_framework" in p.SEGREGATION_PROMPT
    assert "is_pharmacy_bill" in p.SEGREGATION_PROMPT
    # Bills: assembled from blocks (rules + steps + examples + schema).
    assert "BillExtract-AI" in p.PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR
    assert "CRITICAL IP/ER/DG/IPD NUMBER IDENTIFICATION" in p.PHARMACY_BILL_STRUCTURED_DATA_EXTRACTOR
    assert "CRITICAL PACKAGE / BREAKUP HANDLING" in p.CONSOLIDATED_BILL_STRUCTURED_DATA_EXTRACTOR
    # items_categorisation: the full category table (ICU..Donar Charges).
    assert "Donar Charges" in p.ITEMS_CATEGORISATION_SYSTEM_PROMPT
    assert "Medicines Supplied By Hospital" in p.ITEMS_CATEGORISATION_SYSTEM_PROMPT
    # NME: the full non-medical-expenses catalogue is present.
    assert "non_medical_expenses" in p.NME_ANALYSIS_SYSTEM_PROMPT
    assert "Luxury Tax" in p.NME_ANALYSIS_SYSTEM_PROMPT
    assert "NME-AI" in p.NME_ANALYSIS_SYSTEM_PROMPT
    assert "DMO Charges" in p.NME_FALSE_POSITIVES  # false-positive guard block present
    # Audit OPD: medical legibility + ICD + policy rules + 9 examples.
    assert "medical_legibility_opd" in p.AUDIT_SYSTEM_PROMPT_OPD
    assert "icd_codes_extraction" in p.AUDIT_SYSTEM_PROMPT_OPD
    assert "ICD Codes Extraction" in p.AUDIT_SYSTEM_PROMPT_OPD or "Example 9" in p.AUDIT_SYSTEM_PROMPT_OPD
    # benefit_plan: the verbatim ekincare prompt (diagnosis-gated episode grouping).
    assert "DIAGNOSIS-GATED EPISODE GROUPING" in p.BENEFIT_PLAN_SYSTEM_PROMPT


def test_audit_prompt_fills_placeholders():
    from app.tasks.prompts.opd_healthpay import build_audit_prompt

    prompt = build_audit_prompt(
        claimed_amount=1000, calculated_total=950.5, extracted_json='{"bills": []}'
    )
    assert "{{CLAIMED_AMOUNT}}" not in prompt
    assert "1000" in prompt and "950.5" in prompt
    assert "Root canal treatment is covered under OPD" in prompt  # default policy rules filled


def test_opd_schemas_round_trip_aliases():
    from app.tasks.schemas.opd_healthpay import (
        ItemsCategorisationOutput,
        NMEAnalysisResponse,
    )

    cats = ItemsCategorisationOutput.model_validate(
        {"bill_item_categories": [{"bill_id": "B1", "categorized_items": [{"s.no.": 1, "category": "Room Rent"}]}]}
    )
    assert cats.bill_item_categories[0].categorized_items[0].serial_no == 1

    nme = NMEAnalysisResponse.model_validate(
        {"nme_list": [{"nme_item": {"sr.no": 2, "item_name": "Razor", "bill_amount": 5.0, "deduction_reason": "Not Payable"}}]}
    )
    assert nme.nme_list[0].nme_item.serial_no == 2


def test_text_pipe_wiring_consumes_upstream():
    from app.tasks.opd import build_text_inputs

    itemized = {"bills": [{"bill": {"invoice_number": "RX1"}, "items": [{"item_name": "Tab A", "final_amount": 50}]}]}
    categorised = {"bill_item_categories": [{"bill_id": "RX1", "categorized_items": [{"s.no.": 1, "category": "Medicines From Shop"}]}]}
    inputs = build_text_inputs(itemized=itemized, consolidated=None, categorised=categorised)
    # nme input is keyed off the categorised bills (category propagated onto the item).
    assert "Medicines From Shop" in inputs["nme_analysis"]
    # items_categorisation input carries the slim bill payload.
    assert "RX1" in inputs["items_categorisation"]
    # benefit_plan input carries the assembled bills + (empty) benefits.
    assert "benefits" in inputs["benefit_plan"]


# ---- claim-type layer ----
def test_opd_claim_type_wired():
    pack = get_task_pack("OPD")
    assert "audit" in pack


def test_ipd_aliases_and_pack_is_wired():
    assert resolve_claim_type("IPD") == "CL"
    assert resolve_claim_type("MR") == "RM"
    assert "audit" in get_task_pack("IPD")
    assert "audit" in get_task_pack("RM")


# ---- rasterizing adapter (Phase 2) ----
def test_rasterizing_adapter_keeps_pages_under_grok_cap(synthetic_pdf):
    adapter = RasterizingAdapter(_grok_like_cap())
    out = adapter.normalize(
        system="s",
        instruction="extract",
        documents=[DocumentInput(path=synthetic_pdf)],
    )
    assert out.transport == "rasterized_images"
    assert out.image_count == 3  # 3-page synthetic PDF
    # every image block is a base64 data URI; the doc-prep toolkit kept each under 4 MB
    for block in out.content[1:]:
        assert block["type"] == "image_url"
        b64 = block["image_url"]["url"].split(",", 1)[1]
        import base64 as _b64

        assert base64_size_mb(_b64.b64decode(b64)) <= 4.0


def test_context_budget_caps_multipage_packet():
    """A small context window forces a per-page MP cap so all pages' tokens fit (always-on)."""
    from app.providers.adapters.rasterizing import _MIN_PAGE_MEGAPIXELS

    cap = _grok_like_cap().model_copy(update={"context_window": 26032})
    adapter = RasterizingAdapter(cap)
    # No window -> no budget; a window -> budget shrinks as pages grow, floored for legibility.
    no_window = RasterizingAdapter(_grok_like_cap().model_copy(update={"context_window": None}))
    assert no_window._context_budget_megapixels(10) is None
    b3 = adapter._context_budget_megapixels(3)
    b10 = adapter._context_budget_megapixels(10)
    b23 = adapter._context_budget_megapixels(23)
    assert b3 > b10 > b23  # more pages -> tighter per-page cap
    assert b23 >= _MIN_PAGE_MEGAPIXELS  # never below the legibility floor
    # Total estimated vision tokens across pages stays under the window (with reserve headroom).
    tokens_per_mp = 1_000_000 / (28 * 28)
    assert 10 * b10 * tokens_per_mp < 26032


def test_compression_toggle_tightens_megapixel_cap(synthetic_pdf):
    """With compression enabled the adapter downscales to the smaller of catalog cap / request."""
    from app.providers.docprep import megapixels
    from app.utils.pdf import pdf_to_images

    adapter = RasterizingAdapter(_grok_like_cap())  # catalog cap = 33 MP
    original_mp = max(megapixels(img) for img in pdf_to_images(synthetic_pdf))

    off = adapter.normalize(
        system="s", instruction="extract",
        documents=[DocumentInput(path=synthetic_pdf)],
    )
    on = adapter.normalize(
        system="s", instruction="extract",
        documents=[DocumentInput(path=synthetic_pdf)],
        config={"compression": {"enabled": True, "max_megapixels": 1.0}},
    )
    assert off.notes["compressed"] is False
    assert on.notes["compressed"] is True
    # request (1 MP) is smaller than the catalog cap (33 MP), so it wins.
    assert on.notes["max_image_megapixels"] == 1.0
    # and the compressed payload is no larger than the uncompressed one.
    assert on.sent_payload_mb <= off.sent_payload_mb
    del original_mp


def test_text_only_model_gated_out_of_pdf_task_via_adapter(synthetic_pdf):
    from app.providers.adapters import get_adapter

    adapter = get_adapter(_text_only_cap())
    with pytest.raises(CapabilityGateError):
        adapter.normalize(system="s", instruction="x", documents=[DocumentInput(path=synthetic_pdf)])


def test_get_adapter_routes_by_capability():
    from app.providers.adapters import (
        GeminiVertexAdapter,
        RasterizingAdapter,
        TextOnlyAdapter,
        get_adapter,
    )
    from app.providers.registry import registry

    assert isinstance(get_adapter(registry["vertex_ai/gemini-2.5-flash"]), GeminiVertexAdapter)
    assert isinstance(get_adapter(_grok_like_cap()), RasterizingAdapter)
    assert isinstance(get_adapter(_text_only_cap()), TextOnlyAdapter)

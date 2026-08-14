# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/schemas/bills.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FacilityDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    registration_number: str | None
    gst_number: str | None = Field(
        default=None,
        description=(
            "Provider/facility GST or tax registration number printed on the bill/invoice/receipt. Null if absent."
        ),
    )
    address_line: str | None = Field(
        default=None,
        description=("Provider/facility street address as printed on the bill/invoice/receipt header. Null if absent."),
    )
    city: str | None = Field(default=None, description="Provider/facility city. Null if absent.")
    state: str | None = Field(default=None, description="Provider/facility state. Null if absent.")
    pincode: str | None = Field(default=None, description="Provider/facility postal/PIN code. Null if absent.")


class BillHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_name: str | None = Field(
        description="Full name of the patient printed on the invoice/bill. Null if not visible."
    )
    invoice_number: str | None
    ip_number: str | None
    bill_date: str | None = Field(description="Bill/invoice date in YYYY-MM-DD format. Null if not visible.")
    total_discount: float | None = Field(
        description=(
            "Bill-level discount total printed in the bill summary (labelled Discount, "
            "Less, Rebate, Concession). Capture this even when it is not attributed to "
            "individual line items. Null if no bill-level discount is shown."
        ),
    )
    net_amount: float | None = Field(
        description=(
            "Bill-level net/payable total AFTER discount printed in the bill summary "
            "(labelled Net Amount, Net Payable, Amount Received, Grand Total after "
            "discount). Null if not shown."
        ),
    )
    page_number: int | None
    facility_details: FacilityDetails | None


class ItemizedBillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_name: str
    unit_price: float | None = Field(
        description="Per-unit/rate/MRP price when shown. Do not confuse with the total line amount.",
    )
    quantity: float | None = Field(description="Number of units purchased when shown. Numeric only.")
    discount: float | None = Field(
        description="Discount amount for the item. May be labelled rebate, concession, less, or scheme discount.",
    )
    final_amount: float = Field(
        description=(
            "STRICT: gross/listed TOTAL LINE AMOUNT before item discount. Use the printed line total; "
            "if no line total is printed but unit price and quantity are shown, use unit_price * quantity. "
            "If both original and after-discount amounts are shown, use the original/larger amount, "
            "NEVER the post-discount value."
        )
    )
    net_amount: float | None = Field(
        description="Item amount after discount, only if explicitly shown. Otherwise null.",
    )
    is_returned: bool | None


class ItemizedBillGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bill: BillHeader
    items: list[ItemizedBillItem]


class ItemizedBillsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bills: list[ItemizedBillGroup]


class ConsolidatedBillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_name: str
    unit_price: float | None = Field(
        description="Per-unit/rate price when shown. Do not confuse with the total line amount.",
    )
    quantity: float | None = Field(description="Number of units when shown. Numeric only.")
    discount: float | None = Field(
        description="Discount amount for the item. May be labelled rebate, concession, less, or scheme discount.",
    )
    final_amount: float = Field(
        description=(
            "STRICT: gross/listed TOTAL LINE AMOUNT before any discount, rebate, or concession. "
            "If the bill shows both an original and a discounted amount, use the ORIGINAL (larger) amount. "
            "If unit price and quantity are shown with a printed line total, use the printed line total; "
            "if no line total is printed, use unit_price * quantity. NEVER put the post-discount value here."
        )
    )
    net_amount: float | None = Field(
        description="Item amount after discount, only if explicitly shown. Otherwise null.",
    )
    is_returned: bool | None


class ConsolidatedBillGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bill: BillHeader
    items: list[ConsolidatedBillItem]


class ConsolidatedBillsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bills: list[ConsolidatedBillGroup]


class CategorisedBillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None
    amount: float | None
    category: str
    is_medical: bool
    rationale: str | None
    s_no: int | None = Field(alias="s.no.")


class BillCategoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serial_no: int = Field(alias="s.no.")
    category: str


class BillItemCategoryGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bill_id: str
    categorized_items: list[BillCategoryItem]


class ItemsCategorisationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bill_item_categories: list[BillItemCategoryGroup]


class NmeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None
    amount: float | None
    nme_status: Literal["eligible", "non_medical", "uncertain"]
    rationale: str
    serial_no: int | None = Field(alias="s.no.")


class NmeItemDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serial_no: int = Field(alias="sr.no")
    item_name: str
    bill_amount: float
    deduction_reason: str


class NmeListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nme_item: NmeItemDetails


class NmePolicyViolation(BaseModel):
    """Client/insurer policy-rule violation detected by the NME agent."""

    model_config = ConfigDict(extra="forbid")

    rule_name: str | None
    item_name: str | None
    bill_id: str | None
    item_s_no: int | None
    violation_details: str | None
    amount_impacted: float
    recommendation: str | None


class NmeAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nme_list: list[NmeListItem]
    # Populated only for the ekincare OPD flow (policy-rule context provided).
    # Empty for every other project/claim type.
    policy_violations: list[NmePolicyViolation]


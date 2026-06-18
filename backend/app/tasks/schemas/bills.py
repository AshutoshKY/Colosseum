"""Itemized-bills schemas — vendored as-is from superclaims-ai ``schemas/bills.py``.

These are already model-neutral Pydantic v2 schemas and are the *mandatory* structured output
for the ``itemized_bills`` task. Kept verbatim (field descriptions intact) so cross-model
comparisons run against the exact contract the production pipeline uses.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FacilityDetails(BaseModel):
    name: str | None = Field(default=None)
    registration_number: str | None = Field(default=None)


class BillHeader(BaseModel):
    invoice_number: str | None = Field(default=None)
    ip_number: str | None = Field(default=None)
    bill_date: str | None = Field(default=None)
    total_discount: float | None = Field(
        default=None,
        description=(
            "Bill-level discount total printed in the bill summary (labelled Discount, "
            "Less, Rebate, Concession). Capture this even when it is not attributed to "
            "individual line items. Null if no bill-level discount is shown."
        ),
    )
    net_amount: float | None = Field(
        default=None,
        description=(
            "Bill-level net/payable total AFTER discount printed in the bill summary "
            "(labelled Net Amount, Net Payable, Amount Received, Grand Total after "
            "discount). Null if not shown."
        ),
    )
    page_number: int | None = Field(default=None)
    facility_details: FacilityDetails | None = Field(default=None)


class ItemizedBillItem(BaseModel):
    item_name: str
    unit_price: float | None = Field(
        default=None,
        description="Per-unit/rate/MRP price when shown. Do not confuse with the total line amount.",
    )
    quantity: float | None = Field(default=None, description="Number of units purchased when shown. Numeric only.")
    discount: float | None = Field(
        default=None,
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
        default=None,
        description="Item amount after discount, only if explicitly shown. Otherwise null.",
    )
    is_returned: bool | None = Field(default=None)


class ItemizedBillGroup(BaseModel):
    bill: BillHeader
    items: list[ItemizedBillItem]


class ItemizedBillsOutput(BaseModel):
    bills: list[ItemizedBillGroup]

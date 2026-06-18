"""Itemized-bills prompt — vendored from superclaims-ai ``prompts/bills.py`` and de-tuned.

The core task logic and amount-extraction rules are preserved verbatim (they encode the
business contract). Only model-specific framing is neutralized: the prompt makes no assumption
about *how* the document arrives (native PDF vs rasterized images), so it runs identically
across providers. Schema-shape guidance is left to Instructor + the Pydantic schema.
"""

from __future__ import annotations

_BILL_AMOUNT_RULES = """
**AMOUNT EXTRACTION RULES (CRITICAL):**
- unit_price: the per-unit/rate/MRP price when shown. Do not confuse this with the total line amount.
- quantity: number of units purchased when shown. Use numeric values only.
- discount: the discount amount of the item. Discount may also be written as rebate, concession, less,
  scheme discount, or discount amount.
- final_amount: STRICT RULE - this must be the GROSS / LISTED TOTAL LINE AMOUNT before item discount is
  subtracted. If the row shows unit_price and quantity plus a line total, use the printed line total.
  If no line total is printed but unit_price and quantity are shown, use unit_price * quantity.
  If both an original amount and an after-discount amount are shown, use the original/larger amount here,
  NOT the after-discount value.
- net_amount: the item amount after discount only if explicitly shown. If not shown, set it to null.
- When a row has both a unit price and a total/line amount, never use the unit price as final_amount.
  final_amount must be the row total for all units before discount.
- Example: unit price 100, quantity 3, total 300, discount 20, net 280 ->
  unit_price=100, quantity=3, final_amount=300, discount=20, net_amount=280.
- Example: bill shows total 1550 and after discount 1500 -> final_amount=1550, discount=50, net_amount=1500.
- Differentiate between unit price and MRP where both are provided.

**BILL-LEVEL TOTALS (CRITICAL):**
- total_discount (bill header): the bill-level discount printed in the bill summary
  (labelled Discount, Less, Rebate, Concession). Capture this even when the discount is
  shown only as a single bill total and is NOT broken down per line item. Null if absent.
- net_amount (bill header): the bill-level net/payable total AFTER discount (labelled
  Net Amount, Net Payable, Amount Received, Grand Total after discount). Null if absent.
- Example: items total 6150, Discount 850, Net Amount 5300 -> total_discount=850,
  net_amount=5300 on the bill header (line items keep their pre-discount final_amount).
"""

# De-tuned system prompt: no provider-specific phrasing; document arrives via the adapter layer.
ITEMIZED_BILLS_SYSTEM_PROMPT = f"""You are a precise medical-bill extraction assistant.
Analyze the provided itemized bill pages and extract every individual line item.
Each medication, service, consumable, or charge must be its own separate entry in the items list.
Read all numeric values carefully and apply the rules below exactly.
{_BILL_AMOUNT_RULES}"""

ITEMIZED_BILLS_INSTRUCTION = (
    "Extract all itemized bills and their line items from the attached document. "
    "Group line items under the bill they belong to. Return the structured result only."
)

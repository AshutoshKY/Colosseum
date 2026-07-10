# Source: healthpay-ai@test-fhpl healthpay/backend/app/lang_graph/models/pharmacy_bill.py
# ruff: noqa
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import date


class PharmacyBillItem(BaseModel):
    """Model for a single item in a pharmacy bill."""
    s_no: int = Field(..., description="Serial number")
    bill_id: str = Field(..., description="Bill or invoice number")
    ip_number: Optional[str] = Field(None, description="In-Patient Number or Hospital ID if available")
    bill_date: Optional[date] = Field(None, description="Date of the bill")
    item_name: str = Field(..., description="Name or description of the product or service")
    batch_number: Optional[str] = Field(None, description="Batch number if available")
    unit_price: float = Field(..., description="Individual item price before quantity")
    quantity: float = Field(..., description="Quantity of the item")
    discount_percentage: Optional[float] = Field(None, description="Discount percentage if available")
    discount_amount: Optional[float] = Field(None, description="Discount amount if available")
    final_amount: float = Field(..., description="Total amount for the item after quantity and discounts")
    item_type: Literal["MEDICATION", "CONSUMABLE", "SERVICE", "UNKNOWN"] = Field(
        ..., description="Category of the item"
    )
    notes: Optional[str] = Field(None, description="Additional relevant information")


class PharmacyBillStructuredData(BaseModel):
    """Model for structured data extracted from pharmacy bills."""
    items: List[PharmacyBillItem] = Field(..., description="List of items in the pharmacy bill") 

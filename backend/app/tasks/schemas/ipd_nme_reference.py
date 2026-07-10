# Source: healthpay-ai@test-fhpl healthpay/backend/app/lang_graph/models/nme_analysis.py
# ruff: noqa
from typing import List, Optional
from pydantic import BaseModel, Field


class NMEItem(BaseModel):
    """Model for a single item in the NME analysis table."""
    s_no: int = Field(..., description="Serial number")
    item_name: str = Field(..., description="Item name or description")
    bill_amount: float = Field(..., description="Total bill amount for the category in INR")
    deductible_amount: float = Field(..., description="Total NME amount for the category in INR")
    admissible_amount: float = Field(..., description="Bill amount minus deductible amount in INR")
    deduction_reason: Optional[str] = Field(None, description="Reason for deduction, including exclusion numbers")


class NMEAnalysisResponse(BaseModel):
    """Model for the full NME analysis response."""
    items: List[NMEItem] = Field(..., description="List of items in the NME analysis") 

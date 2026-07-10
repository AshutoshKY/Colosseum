# Source: healthpay-ai@test-fhpl healthpay/backend/app/lang_graph/models/document_segregator.py
# ruff: noqa
from typing import List, Dict, Optional
from pydantic import BaseModel, Field


class CriticalElements(BaseModel):
    """Model for critical elements in document segments."""
    missing_information: List[str] = Field(default_factory=list, 
                                         description="List of missing information items")
    unclear_elements: List[str] = Field(default_factory=list, 
                                       description="List of unclear elements in the document")


class DocumentSegment(BaseModel):
    """Model for document segments in the segregator response."""
    document_type: str = Field(..., 
                             description="Type of document from predefined categories")
    pages: str = Field(...,
                     description="Compact page range string such as '1-3,5,8-10'")
    # summary: str = Field(..., 
                    #    description="Brief description of document content")
    format: str = Field(..., 
                      description="Format type: handwritten, printed, or mixed")
    additional_notes: List[str] = Field(default_factory=list, 
                                      description="Additional observations about the document")
    quality_assessment: str = Field(..., 
                                  description="Assessment of document quality")
    critical_elements: CriticalElements = Field(default_factory=CriticalElements, 
                                              description="Critical elements assessment")


class OverallAssessment(BaseModel):
    """Model for overall assessment of document package."""
    completeness: str = Field(..., 
                            description="Assessment of overall package completeness")
    quality: str = Field(..., 
                       description="Overall quality assessment")
    recommendations: List[str] = Field(default_factory=list, 
                                     description="Recommendations for document package")


class DocumentSegregatorResponse(BaseModel):
    """Model for the full response from document segregator agent."""
    total_pages: int = Field(..., 
                           description="Total number of pages in the document")
    segments: List[DocumentSegment] = Field(..., 
                                          description="List of document segments")
    overall_assessment: OverallAssessment = Field(..., 
                                                description="Overall assessment of document package") 

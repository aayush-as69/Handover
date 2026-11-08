"""Pydantic schemas.

ExtractedClaim is the contract the AI extraction step must satisfy. Anything that does not
validate is rejected, so malformed model output never reaches the claim store.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import ClaimType, Confidence, ReviewStatus, Sensitivity, Stance


class EvidenceIn(BaseModel):
    chunk_id: int
    snippet: str = Field(min_length=1, description="Exact text copied from the chunk")
    stance: Stance = Stance.supports


class ExtractedClaim(BaseModel):
    statement: str = Field(min_length=3)
    type: ClaimType
    topic: Optional[str] = None
    value: Optional[str] = None
    owner: Optional[str] = None
    # A claim with no valid evidence is dropped by the extraction pipeline, never stored.
    evidence: list[EvidenceIn] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: int
    snippet: str
    stance: Stance
    snippet_verified: Optional[bool]


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    statement: str
    type: ClaimType
    topic: Optional[str]
    value: Optional[str]
    owner: Optional[str]
    confidence: Confidence
    sensitivity: Sensitivity
    review_status: ReviewStatus
    version: int
    evidence: list[EvidenceOut] = Field(default_factory=list)

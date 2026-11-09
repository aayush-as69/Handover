"""Pydantic schemas.

ExtractedClaim is the contract the AI extraction step must satisfy. Anything that does not
validate is rejected, so malformed model output never reaches the claim store.
"""

from __future__ import annotations

from typing import Optional

import re

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from .enums import ClaimType, Confidence, ReviewStatus, Sensitivity, Stance


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_CLAIMS_PER_REPLY = 200


def _clean(v: str) -> str:
    return _CONTROL.sub("", v).strip()


class EvidenceIn(BaseModel):
    """Model output is untrusted: exact types, bounded sizes, no control characters."""

    chunk_id: StrictInt                      # a JSON string, float or boolean is rejected
    snippet: StrictStr = Field(min_length=1, max_length=2000,
                               description="Exact text copied from the chunk")
    stance: Stance = Stance.supports

    @field_validator("snippet")
    @classmethod
    def _snippet(cls, v: str) -> str:
        v = _clean(v)
        if not v:
            raise ValueError("snippet is empty")
        return v


class ExtractedClaim(BaseModel):
    statement: StrictStr = Field(min_length=3, max_length=1000)
    type: ClaimType
    topic: Optional[StrictStr] = Field(default=None, max_length=120)
    value: Optional[StrictStr] = Field(default=None, max_length=200)
    owner: Optional[StrictStr] = Field(default=None, max_length=128)
    # A claim with no valid evidence is dropped by the extraction pipeline, never stored.
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=10)

    @field_validator("statement")
    @classmethod
    def _statement(cls, v: str) -> str:
        v = " ".join(_clean(v).split())
        if len(v) < 3:
            raise ValueError("statement is empty")
        return v

    @field_validator("topic", "value", "owner")
    @classmethod
    def _short(cls, v):
        return (_clean(v) or None) if v is not None else None


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

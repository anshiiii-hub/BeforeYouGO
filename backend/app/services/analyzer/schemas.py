from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import ClaimCategory, ClaimType


class LLMClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    original_text: str = Field(min_length=8, max_length=600)
    normalized_text: str = Field(min_length=5, max_length=500)
    category: ClaimCategory
    claim_type: ClaimType
    responsible_party: str | None = Field(default=None, max_length=300)
    conditions: list[str] = Field(default_factory=list, max_length=10)
    missing_details: list[str] = Field(default_factory=list, max_length=10)
    verification_questions: list[str] = Field(default_factory=list, max_length=6)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("conditions", "missing_details", "verification_questions")
    @classmethod
    def _short_items(cls, v: list[str]) -> list[str]:
        return [s.strip()[:300] for s in v if isinstance(s, str) and s.strip()]


class LLMExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[LLMClaim] = Field(max_length=40)

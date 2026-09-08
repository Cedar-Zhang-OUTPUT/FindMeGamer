"""Small English-only AI interpretations with explicit supplied-source citations."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class XAvailableClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available"]
    text: str = Field(min_length=1, max_length=800)
    cited_source_ids: list[str] = Field(min_length=1, max_length=10)
    kind: Literal["ai_inference"]


class XUnavailableClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unavailable"]
    reason: str = Field(min_length=1, max_length=300)


XClaim = Annotated[XAvailableClaim | XUnavailableClaim, Field(discriminator="status")]


class XAnalysisSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    english_language_check: Literal[True]
    content_summary: XClaim
    content_style: XClaim
    audience_inference: XClaim
    promotion_fit: XClaim
    brand_safety: XClaim


def require_x_citations(value: XAnalysisSignals, available_ids: set[str]):
    from app.integrations.errors import InvalidModelOutput

    for name in (
        "content_summary",
        "content_style",
        "audience_inference",
        "promotion_fit",
        "brand_safety",
    ):
        claim = getattr(value, name)
        if (
            isinstance(claim, XAvailableClaim)
            and not set(claim.cited_source_ids) <= available_ids
        ):
            raise InvalidModelOutput("deepseek_model_evidence_invalid")
